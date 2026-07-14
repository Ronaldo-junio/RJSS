#!/bin/bash

if [ -f /tmp/rjss_app.pid ]; then
    kill "$(cat /tmp/rjss_app.pid)" 2>/dev/null && echo "app.py encerrado." || echo "app.py já não estava rodando."
    rm -f /tmp/rjss_app.pid
else
    echo "PID do app.py não encontrado. Tentando por nome..."
    pkill -f "python3 app.py" && echo "app.py encerrado." || echo "app.py não encontrado."
fi

if [ -f /tmp/rjss_ngrok.pid ]; then
    kill "$(cat /tmp/rjss_ngrok.pid)" 2>/dev/null && echo "ngrok encerrado." || echo "ngrok já não estava rodando."
    rm -f /tmp/rjss_ngrok.pid
else
    echo "PID do ngrok não encontrado. Tentando por nome..."
    pkill -f "ngrok" && echo "ngrok encerrado." || echo "ngrok não encontrado."
fi
