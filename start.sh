#!/bin/bash

# Verifica se o ngrok está instalado
if ! command -v ngrok &> /dev/null
then
    echo "ngrok não encontrado. Instale o ngrok antes de continuar."
    exit 1
fi

# Inicia o ngrok em background e salva o PID
nohup ngrok http 5000 > /dev/null 2>&1 &
echo $! > /tmp/rjss_ngrok.pid

# Inicia o app.py em background e salva o PID
nohup python3 app.py > /dev/null 2>&1 &
echo $! > /tmp/rjss_app.pid

echo "ngrok (PID $(cat /tmp/rjss_ngrok.pid)) e app.py (PID $(cat /tmp/rjss_app.pid)) iniciados."
echo "Para encerrar: ./stop.sh"