import sys
import os

# Define o caminho base da aplicação
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importa a instância da aplicação Flask para o Phusion Passenger
from app import app as application
