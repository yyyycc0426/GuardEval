import asyncio
import streamlit as st
import websockets

st.set_page_config(
    page_title="LLM Security Platform Dashboard",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ LLM Security Platform - WebSocket Console")

# Input Token
token = st.text_input("Enter JWT Authentication Token:", type="password")

if token:
    st.success("Token provided! Connecting to WebSocket...")
    
    async def connect_ws():
        uri = f"ws://localhost:8020/ws?token={token}"
        try:
            async with websockets.connect(uri) as websocket:
                st.info("Connection established! Sending greeting...")
                await websocket.send("Hello from Streamlit Client!")
                response = await websocket.recv()
                st.write("Server Response:")
                st.success(response)
        except Exception as exc:
            st.error(f"WebSocket Connection Failed: {exc}")
            
    asyncio.run(connect_ws())
