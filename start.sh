#!/bin/bash
# 启动前端和后端，自动清理旧进程

echo "清理旧进程..."
taskkill //F //IM python.exe //T 2>/dev/null
taskkill //F //IM node.exe //T 2>/dev/null
sleep 1

echo "启动后端..."
cd "$(dirname "$0")/backend"
python -m uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

echo "等待后端就绪..."
for i in {1..10}; do
  sleep 1
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "后端已就绪 (PID: $BACKEND_PID)"
    break
  fi
done

echo "启动前端..."
cd "$(dirname "$0")/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "服务已启动："
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待，Ctrl+C 时清理
trap "echo '停止服务...'; taskkill //F //IM python.exe //T 2>/dev/null; taskkill //F //IM node.exe //T 2>/dev/null" EXIT
wait
