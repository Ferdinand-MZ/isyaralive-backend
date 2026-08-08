from app.services.detector import GestureDetector

# Singleton — model LSTM & MediaPipe cuma diload sekali saat startup,
# dipakai bersama oleh WebSocket /ws/detect DAN AI Chatbot (upload video).
detector = GestureDetector()