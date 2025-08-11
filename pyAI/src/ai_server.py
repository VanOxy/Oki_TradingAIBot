import grpc
from concurrent import futures
import aimodelservice_pb2
import aimodelservice_pb2_grpc
import time

class AIModelService(aimodelservice_pb2_grpc.AIModelServiceServicer):
    
    def SendTriggerData(self, request, context):
        print(f"[TRIGGER] {request.symbol} → {request.trigger_features}")
        score = self._process_trigger(request.symbol, request.trigger_features)
        return aimodelservice_pb2.AIResponse(symbol=request.symbol, score=score)
    
    def SendMarketData(self, request, context):
        print(f"[MARKET] {request.symbol} → {request.market_features}")
        score = self._process_market(request.symbol, request.market_features)
        return aimodelservice_pb2.AIResponse(symbol=request.symbol, score=score)
    
    def AnalyzeTrade(self, request, context):
        # Декодируем изображение (если нужно)
        #with open("received_chart.png", "wb") as f:
            #f.write(request.chart_image)

        print(f"📈 Получена сделка: {request.symbol} @ {request.price} ({request.timestamp})")

        # Здесь могла бы быть твоя ML-модель
        decision = "BUY" if request.price < 30000 else "SELL"
        confidence = 0.85

        return aimodelservice_pb2.TradeResponse(decision=decision, confidence=confidence)
    
    def _process_trigger(self, symbol, features):
        # Здесь будет твоя модель под триггеры
        return 0.5  # пока мок

    def _process_market(self, symbol, features):
        # Здесь будет твоя модель под рынок
        return 0.7  # пока мок

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    aimodelservice_pb2_grpc.add_AIModelServiceServicer_to_server(AIModelService(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("✅ gRPC AI Server started on port 50051")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == "__main__":
    serve()
