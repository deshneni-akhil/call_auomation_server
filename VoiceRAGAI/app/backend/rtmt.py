import asyncio
import base64
import json
import logging
import os
from enum import Enum
from typing import Any, Callable, Optional

import aiohttp
from aiohttp import web, WSMessage
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from logger import MultiLogger

logger_manager = MultiLogger("rtmt", log_level=logging.ERROR)

logger_manager.change_log_destination("file", "logs/rtmt-acs.log")

logger = logger_manager.get_logger()


class ToolResultDirection(Enum):
    TO_SERVER = 1
    TO_CLIENT = 2

class ToolResult:
    text: str
    destination: ToolResultDirection

    def __init__(self, text: str, destination: ToolResultDirection):
        self.text = text
        self.destination = destination

    def to_text(self) -> str:
        if self.text is None:
            return ""
        return self.text if type(self.text) == str else json.dumps(self.text)

class Tool:
    target: Callable[..., ToolResult]
    schema: Any

    def __init__(self, target: Any, schema: Any):
        self.target = target
        self.schema = schema

class RTToolCall:
    tool_call_id: str
    previous_id: str

    def __init__(self, tool_call_id: str, previous_id: str):
        self.tool_call_id = tool_call_id
        self.previous_id = previous_id

class RTMiddleTier:
    endpoint: str
    deployment: str
    key: Optional[str] = None
    
    # Tools are server-side only for now, though the case could be made for client-side tools
    # in addition to server-side tools that are invisible to the client
    tools: dict[str, Tool] = {}

    # Server-enforced configuration, if set, these will override the client's configuration
    # Typically at least the model name and system message will be set by the server
    model: Optional[str] = None
    system_message: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    disable_audio: Optional[bool] = None
    voice_choice: Optional[str] = None
    api_version: str = "2024-10-01-preview"
    _tools_pending = {}
    _token_provider = None

    def __init__(self, endpoint: str, deployment: str, credentials: AzureKeyCredential | DefaultAzureCredential, voice_choice: Optional[str] = None):
        self.endpoint = endpoint
        self.deployment = deployment
        self.voice_choice = voice_choice
        if voice_choice is not None:
            logger.info("Realtime voice choice set to %s", voice_choice)
        if isinstance(credentials, AzureKeyCredential):
            self.key = credentials.key
        else:
            self._token_provider = get_bearer_token_provider(credentials, "https://cognitiveservices.azure.com/.default")
            self._token_provider() # Warm up during startup so we have a token cached when the first request arrives

    async def _process_message_to_client(self, msg: WSMessage, client_ws: web.WebSocketResponse, server_ws: web.WebSocketResponse) -> Optional[str]:
        message = json.loads(msg.data)
        updated_message = msg.data
        # print("Received message from OpenAI:", message)
        logger.info("Received message from server: %s", message)
        if message is not None:
            match message["type"]:
                case "session.created":
                    session = message["session"]
                    # Hide the instructions, tools and max tokens from clients, if we ever allow client-side 
                    # tools, this will need updating
                    session["instructions"] = ""
                    session["tools"] = []
                    session["voice"] = self.voice_choice
                    session["tool_choice"] = "none"
                    session["max_response_output_tokens"] = None
                    updated_message = json.dumps(message)

                case "response.output_item.added":
                    if "item" in message and message["item"]["type"] == "function_call":
                        updated_message = None

                case "conversation.item.created":
                    if "item" in message and message["item"]["type"] == "function_call":
                        item = message["item"]
                        if item["call_id"] not in self._tools_pending:
                            self._tools_pending[item["call_id"]] = RTToolCall(item["call_id"], message["previous_item_id"])
                        updated_message = None
                    elif "item" in message and message["item"]["type"] == "function_call_output":
                        updated_message = None

                case "response.function_call_arguments.delta":
                    updated_message = None
                
                case "response.function_call_arguments.done":
                    updated_message = None

                case "response.output_item.done":
                    if "item" in message and message["item"]["type"] == "function_call":
                        item = message["item"]
                        tool_call = self._tools_pending[message["item"]["call_id"]]
                        tool = self.tools[item["name"]]
                        args = item["arguments"]
                        result = await tool.target(json.loads(args))
                        await server_ws.send_json({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": item["call_id"],
                                "output": result.to_text() if result.destination == ToolResultDirection.TO_SERVER else ""
                            }
                        })
                        if result.destination == ToolResultDirection.TO_CLIENT:
                            # TODO: this will break clients that don't know about this extra message, rewrite 
                            # this to be a regular text message with a special marker of some sort
                            await client_ws.send_json({
                                "type": "extension.middle_tier_tool_response",
                                "previous_item_id": tool_call.previous_id,
                                "tool_name": item["name"],
                                "tool_result": result.to_text()
                            })
                        updated_message = None

                case "response.done":
                    if len(self._tools_pending) > 0:
                        self._tools_pending.clear() # Any chance tool calls could be interleaved across different outstanding responses?
                        await server_ws.send_json({
                            "type": "response.create"
                        })
                    if "response" in message:
                        replace = False
                        for i, output in enumerate(reversed(message["response"]["output"])):
                            if output["type"] == "function_call":
                                message["response"]["output"].pop(i)
                                replace = True
                        if replace:
                            updated_message = json.dumps(message)                        
        # print("Sending message to client:", updated_message)
        return updated_message

    async def _process_message_to_server(self, msg: str, ws: web.WebSocketResponse) -> Optional[str]:
        message = json.loads(msg.data)
        updated_message = msg.data
        # print("Received message from client:", message)
        logger.info("Received message from client: %s", message)
        if message is not None:
            match message["type"]:
                case "session.update":
                    session = message["session"]
                    if self.system_message is not None:
                        session["instructions"] = self.system_message
                    if self.temperature is not None:
                        session["temperature"] = self.temperature
                    if self.max_tokens is not None:
                        session["max_response_output_tokens"] = self.max_tokens
                    if self.disable_audio is not None:
                        session["disable_audio"] = self.disable_audio
                    if self.voice_choice is not None:
                        session["voice"] = self.voice_choice
                    session["tool_choice"] = "auto" if len(self.tools) > 0 else "none"
                    session["tools"] = [tool.schema for tool in self.tools.values()]
                    logger.info("updated message:", message)
                    # print("updated message:", message)
                    updated_message = json.dumps(message)

        # print("Sending message to OpenAI:", updated_message)
        return updated_message
    
    async def transmit_openai_audio_to_acs(self, gpt_audio_response: str):
        """
        Extracts audio data from OpenAI WebSocket (target_ws) and streams it to the ACS client (client_ws).
        
        Parameters:
            gpt_audio_response (dict): Audio data from OpenAI.
            client_ws (web.WebSocketResponse): WebSocket connection to ACS client.
        """
        acs_payload = {
            "Kind": "AudioData",
            "AudioData": {
                "Data": gpt_audio_response
            },
            "StopAudio": None
        }
        # Forward the audio to ACS
        # logger.info("Sending audio data to ACS: %s", acs_payload)
        serialized_data = json.dumps(acs_payload)
        return serialized_data

    
    async def update_session_instruction(self) -> None:
        logger.info("Entered update session function")
        payload = {
            "type" : "session.update",
            'session': {
                'turn_detection': {'type': 'server_vad'}
            }
        }
        logger.info("Sending turn detection to server_vad: %s", payload)
        await self.update_session(payload)
        return json.dumps(payload)
    
    async def greet_user(self, server_ws: web.WebSocketResponse):
        greeting_audio_path = os.path.join(os.path.dirname(__file__), 'audio', "greet-user.pcm")
        logger.info("Greeting user with audio: %s", greeting_audio_path)
        try:
            with open(greeting_audio_path, "rb") as audio_file:
                pcm_audio = audio_file.read()
            base64_payload = base64.b64encode(pcm_audio).decode()
            payload = {
                "type": "input_audio_buffer.append",
                "event_id": "greeting",
                "audio": base64_payload
            }
            logger.info("Sending greeting audio to OpenAI: %s", payload)
            await server_ws.send_json(payload)
        except FileNotFoundError:
            logger.error("Greeting audio file not found: %s", greeting_audio_path)
        except Exception as e:
            logger.error("Error reading greeting audio: %s", e)

    async def forward_openai_audio_to_acs(self, server_ws: web.WebSocketResponse, client_ws: web.WebSocketResponse):
        """
        Extracts audio data from OpenAI WebSocket (target_ws) and streams it to the ACS client (client_ws).
        
        Parameters:
            server_ws (aiohttp.ClientWebSocketResponse): WebSocket connection to OpenAI.
            client_ws (web.WebSocketResponse): WebSocket connection to ACS client.
        """
        async for msg in server_ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                # Handle text responses from OpenAI (if needed)
                new_msg = await self._process_message_to_client(msg, client_ws, server_ws)
                new_msg = json.loads(msg.data)
                if new_msg is not None:
                    logger.info("Sending message to client: %s", new_msg)
                    match new_msg.get("type", ""):
                        case "response.audio.delta":
                            gpt_audio_response = new_msg.get("delta", {})
                            # logger_manager.write_instruction_log(gpt_audio_response, "openai_audio.log")
                            client_response = await self.transmit_openai_audio_to_acs(gpt_audio_response)
                            await client_ws.send_str(client_response)
                        case 'session.created':
                            payload = await self.update_session_instruction()
                            logger.info("Sending updated session to OpenAI: %s", payload)
                            await server_ws.send_str(payload)
                            await self.greet_user(server_ws)
                        case 'input_audio_buffer.speech_started':
                            # As the speech has started by the client, we need to clear the audio buffer at the acs side
                            acs_payload = {
                                "Kind": "StopAudio",
                                "AudioData": None,
                                "StopAudio": {}
                            }
                            serialized_data = json.dumps(acs_payload)
                            logger.info("Sending stop audio to ACS: %s", serialized_data)
                            await client_ws.send_str(serialized_data)

            elif msg.type == aiohttp.WSMsgType.CLOSE:
                logger.info("OpenAI WebSocket closed.")
                await client_ws.close()
                break
            else:
                logger.info(f"Received unsupported message type from OpenAI: {msg.type} {msg.data}")

    async def update_session(self, message: dict) -> None:
        logger.info("Entered update session function")
        if message is not None:
            match message["type"]:
                case "session.update":
                    session = message["session"]
                    if self.system_message is not None:
                        session["instructions"] = self.system_message
                    if self.temperature is not None:
                        session["temperature"] = self.temperature
                    if self.max_tokens is not None:
                        session["max_response_output_tokens"] = self.max_tokens
                    if self.disable_audio is not None:
                        session["disable_audio"] = self.disable_audio
                    if self.voice_choice is not None:
                        session["voice"] = self.voice_choice
                    session["tool_choice"] = "auto" if len(self.tools) > 0 else "none"
                    session["tools"] = [tool.schema for tool in self.tools.values()]

    async def forward_from_acs_to_openai(self, server_ws: web.WebSocketResponse, client_ws: web.WebSocketResponse):
        """
        Handles incoming audio data from ACS and forwards it to the OpenAI's WebSocket.
        """
        async for msg in client_ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    message = json.loads(msg.data)
                    logger.info("ACS stream sending to server: %s", message)
                    
                    # Doing an experiment to see if the audio data is being received from acs is correct or not and writing it to a log file
                    if 'kind' in message: 
                        # logger_manager.write_instruction_log(message['audioData']['data'], "acs_audio.log")
                        pass
                    
                    kind = message.get("kind", "")

                    if kind == "AudioData":
                        audio_base64 = message["audioData"]["data"]
                        payload = {
                            'type' : 'input_audio_buffer.append',
                            'audio' : audio_base64
                        }
                        openai_message = json.dumps(payload)
                        await server_ws.send_str(openai_message)
                    else:
                        logger.info("Received unexpected message kind: %s", kind)

                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Error decoding ACS message: {e}")

            elif msg.type == aiohttp.WSMsgType.CLOSE:
                print("ACS WebSocket connection closed.")
                await server_ws.close()
                break
            else:
                print(f"Received unsupported message type from ACS: {msg.type}")


    async def _forward_messages(self, ws: web.WebSocketResponse):
        async with aiohttp.ClientSession(base_url=self.endpoint) as session:
            params = { "api-version": self.api_version, "deployment": self.deployment}
            headers = {}
            if "x-ms-client-request-id" in ws.headers:
                headers["x-ms-client-request-id"] = ws.headers["x-ms-client-request-id"]
            if self.key is not None:
                headers = { "api-key": self.key }
            else:
                headers = { "Authorization": f"Bearer {self._token_provider()}" } # NOTE: no async version of token provider, maybe refresh token on a timer?

            async with session.ws_connect("/openai/realtime", headers=headers, params=params) as target_ws:
                async def from_client_to_server():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            new_msg = await self._process_message_to_server(msg, ws)
                            if new_msg is not None:
                                logger.info("Sending message to server: %s", new_msg)
                                await target_ws.send_str(new_msg)
                        else:
                            print("Error: unexpected message type:", msg.type)
                    
                    # Means it is gracefully closed by the client then time to close the target_ws
                    if target_ws:
                        print("Closing OpenAI's realtime socket connection.")
                        await target_ws.close()
                        
                async def from_server_to_client():
                    async for msg in target_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            new_msg = await self._process_message_to_client(msg, ws, target_ws)
                            if new_msg is not None:
                                logger.info("Sending message to client: %s", new_msg)
                                await ws.send_str(new_msg)
                        else:
                            print("Error: unexpected message type:", msg.type)

                try:
                    # await asyncio.gather(from_client_to_server(), from_server_to_client())
                    await asyncio.gather(self.forward_from_acs_to_openai(target_ws, ws), self.forward_openai_audio_to_acs(target_ws, ws))
                except ConnectionResetError:
                    # Ignore the errors resulting from the client disconnecting the socket
                    pass

    async def _websocket_handler(self, request: web.Request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await self._forward_messages(ws)
        return ws
    
    def attach_to_app(self, app, path):
        logger_manager.truncate_log_files("acs_audio.log")
        logger_manager.truncate_log_files("openai_audio.log")
        app.router.add_get(path, self._websocket_handler)