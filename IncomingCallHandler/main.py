# Python standard library imports
import os
import uuid
import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlencode

# Third-party imports
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv, find_dotenv
import websockets

# Azure imports
from azure.core.messaging import CloudEvent
from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.communication.callautomation import (
    MediaStreamingOptions,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    AudioFormat
)
from azure.communication.callautomation.aio import CallAutomationClient

# find and load the .env file
load_dotenv(find_dotenv())

ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")

CALLBACK_URI_HOST = os.getenv("CALLBACK_URI_HOST")
CALLBACK_EVENTS_URI = CALLBACK_URI_HOST + "/api/callbacks"

TRANSPORT_URL = os.getenv("WEBSOCKET_SERVER")

# print(ACS_CONNECTION_STRING)
call_automation_client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)

# intialize logger
logger = logging.getLogger()

async def check_websocket():
    # Check if the WebSocket server is running before starting the FastAPI server
    try:
        async with websockets.connect(TRANSPORT_URL) as websocket:
            await websocket.ping()
    except:
        raise Exception(f"WebSocket server at {TRANSPORT_URL} is not responding")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # This will prevent the server from starting if the check fails 
    try:
        # Run the check during startup
        await check_websocket()
        yield
        
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")
        raise  

# Initialize the FastAPI app
# The lifespan context manager will check the WebSocket server before starting the FastAPI server
# If the WebSocket server is not running, the FastAPI server will not start
app = FastAPI(
    lifespan=lifespan,
    title="Incoming Call Handler",
    description="An Azure Communication Services call automation app that handles incoming calls and callbacks.",
    version="1.0.0",
    docs_url="/docs",         # URL for Swagger UI
    redoc_url="/redoc",       # URL for ReDoc
    openapi_url="/openapi.json"  # URL for the OpenAPI schema
)

app.mount("/static", StaticFiles(directory="sound_effects"), name="static")

# answer call async fun is responsible for answering the incoming call and setting up the media streaming via websocket
async def answer_call_async(incoming_call_context, callback_url):
    media_streaming_configuration = MediaStreamingOptions(
        transport_url=TRANSPORT_URL,
        transport_type=MediaStreamingTransportType.WEBSOCKET,
        content_type=MediaStreamingContentType.AUDIO,
        audio_channel_type=MediaStreamingAudioChannelType.MIXED,
        start_media_streaming=True,
        enable_bidirectional=True,
        audio_format=AudioFormat.PCM24_K_MONO
    )
    return await call_automation_client.answer_call(
        incoming_call_context=incoming_call_context,
        media_streaming = media_streaming_configuration,
        callback_url=callback_url)


@app.post("/api/incomingCall")
async def incoming_call_handler(request: Request):
    request_json = await request.json()
    for event_dict in request_json:
            event = EventGridEvent.from_dict(event_dict)
            logger.info("incoming event data --> %s", event.data)
            
            if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
                print('event data in validation handler: ', event.data)
                logger.info("Validating subscription")
                validation_code = event.data['validationCode']
                print("Validation code: ", validation_code)
                validation_response = {'validationResponse': validation_code}
                return Response(content=json.dumps(validation_response), status_code=200)
            
            elif event.event_type == "Microsoft.Communication.IncomingCall":
                logger.info("Incoming call received: data=%s", 
                                event.data)  
                if event.data['from']['kind'] =="phoneNumber":
                    caller_id =  event.data['from']["phoneNumber"]["value"]
                else :
                    caller_id =  event.data['from']['rawId'] 
                
                source_number = event.data['to']['phoneNumber']['value']
                logger.info("incoming call handler caller id: %s",
                                caller_id)
                incoming_call_context=event.data['incomingCallContext']
                guid =uuid.uuid4()
                query_parameters = urlencode({"callerId": caller_id})
                callback_uri = f"{CALLBACK_EVENTS_URI}/{guid}/{source_number}?{query_parameters}"

                logger.info("callback url: %s",  callback_uri)

                await check_websocket()
                answer_call_result = await answer_call_async(incoming_call_context, callback_uri)
                
                logger.info("Answered call for connection id: %s",
                                answer_call_result.call_connection_id)
                
                return Response(status_code=200)
            

@app.post("/api/callbacks/{contextId}/{sourceNumber}")
async def handle_callback(request: Request, contextId: str, sourceNumber: str):
    """
    Asynchronously handles various callback events from Microsoft Azure Communication Services.
    This function processes different types of events related to call automation including call connections,
    speech recognition, call transfers, and error handling. It manages the conversation flow between the AI
    and the caller, including sentiment analysis and agent escalation.
    Known Issue: Currently, there's no direct handling of stopping a playing audio before starting a new one.
    Consider implementing audio interruption using call_automation_client.stop_play() before new handle_play calls.
    Reference: https://learn.microsoft.com/en-us/azure/communication-services/concepts/call-automation/call-automation
    Parameters:
        contextId (str): The context identifier for the callback event
    Returns:
        Response: HTTP 200 on successful processing, HTTP 500 on errors
    Events Handled:
        - Microsoft.Communication.CallConnected: Initial call connection
        - Microsoft.Communication.RecognizeCompleted: Speech recognition results
        - Microsoft.Communication.RecognizeFailed: Failed speech recognition
        - Microsoft.Communication.CallTransferAccepted: Successful call transfer
        - Microsoft.Communication.CallTransferFailed: Failed call transfer
    Global Variables Used:
        - caller_id: Stores the caller's phone number
        - max_retry: Controls retry attempts for failed recognitions
    Raises:
        Exception: Catches and logs any unexpected errors during event processing
    Note:
        To stop currently playing audio before starting new playback, implement:
        await call_connection_client.stop_play() before handle_play calls
    """
    try:        
        global caller_id
        request_json = await request.json()
        logger.info("callback event data --> %s", request_json)
        for event_dict in request_json:       
            event = CloudEvent.from_dict(event_dict)
            logger.info("%s event received for call connection id: %s", event.type, event.data['callConnectionId'])
            print("%s event received for call connection id: %s", event.type, event.data['callConnectionId'])
            caller_id = request.query_params.get("callerId").strip()

            call_connection_id = event.data['callConnectionId']
            logger.info("call connection id: %s", call_connection_id)
            if "+" not in caller_id:
                caller_id="+".strip()+caller_id.strip()
            logger.info("call connected : data=%s", event.data)
        return Response(status_code=200) 
    
    except Exception as ex:
        logger.error(f"Error in event handling: {str(ex)}")
        return Response(
            content=json.dumps({"error": "Internal server error"}), 
            status_code=500, 
            media_type="application/json"
        )

@app.get("/health")
async def health_check():
    return Response(content=json.dumps({"status": "healthy"}), media_type="application/json")

@app.get("/")
async def hello():
    payload = {
        'version': app.version,
        'title': app.title,
        'description': app.description,
        'docs_url': app.docs_url,
        'health_check': '/health',
    }
    return Response(content=json.dumps(payload), media_type="application/json")
