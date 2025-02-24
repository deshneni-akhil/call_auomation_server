# Call Automation Server

This application leverages Azure Communication Services to establish a WebSocket connection with a real-time API web server. This connection enables bidirectional communication with an AI agent.

## Prerequisites

- Create an Azure account with an active subscription. For details, see [Create an account for free](https://azure.microsoft.com/free/)
- Create an Azure Communication Services resource. For details, see [Create an Azure Communication Resource](https://docs.microsoft.com/azure/communication-services/quickstarts/create-communication-resource). You'll need to record your resource **connection string** for this sample.
- An Calling-enabled telephone number. [Get a phone number](https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/telephony/get-phone-number?tabs=windows&pivots=platform-azp)
- Create and host a Azure Dev Tunnel. Instructions [here](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/get-started)
- Setup event grid for incoming call. Instruction [here](https://learn.microsoft.com/en-us/azure/communication-services/concepts/call-automation/incoming-call-notification)
- [Python](https://www.python.org/downloads/) 3.7 or above.


## Setting up sample on local environment

1. Clone the repository using:  
    git clone `https://github.com/deshneni-akhil/call_auomation_server.git`.
2. This monorepo contains both the IncomingCallHandler and VoiceRAGAI applications.
3. For this setup, navigate to the IncomingCallHandler directory.

### Setup the Python environment

Create and activate python virtual environment and install required packages using following command 
```
pip install -r requirements.txt
```

### Setup and host your Azure DevTunnel

[Azure DevTunnels](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/overview) is an Azure service that enables you to share local web services hosted on the internet. Use the commands below to connect your local development environment to the public internet. This creates a tunnel with a persistent endpoint URL and which allows anonymous access. We will then use this endpoint to notify your application of calling events from the ACS Call Automation service.

```bash
devtunnel create --allow-anonymous
devtunnel port create -p 8000
devtunnel host
```

### Configuring application

Open `main.py` file to configure the following settings

1. - `CALLBACK_URI_HOST`: your dev tunnel endpoint
2. - `ACS_CONNECTION_STRING`: Azure Communication Service resource's connection string.
3. - `TRANSPORT_URL`: This is devtunnel websocket url for VoiceRAGAI

## Run app locally
1. Open your terminal and run the following command to start the application:
   
   > fastapi dev main.py

2. Once the application starts, your browser should automatically open the application page. If it doesn't, manually navigate to either `http://localhost:8000/` or your designated dev tunnel URL.

3. Register an EventGrid Webhook for the IncomingCall event pointing to your DevTunnel URI. For detailed instructions, refer to the [Azure documentation](https://learn.microsoft.com/en-us/azure/communication-services/concepts/call-automation/incoming-call-notification).

Once that's completed you should have a running application. The best way to test this is to place a call to your ACS phone number and talk to your intelligent agent.