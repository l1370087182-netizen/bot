import ccxt
import time
import os
from dotenv import load_dotenv

load_dotenv()

def test_connection():
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    print(f"Testing connection with API Key: {api_key[:6]}***")
    
    exchange = ccxt.binanceusdm({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'adjustForTimeDifference': True,
            'recvWindow': 60000,
        }
    })
    
    try:
        # 1. Fetch time
        server_time = exchange.fetch_time()
        local_time = int(time.time() * 1000)
        print(f"Server Time: {server_time}")
        print(f"Local Time:  {local_time}")
        print(f"Difference:  {server_time - local_time}ms")
        
        # 2. Fetch balance (requires valid API key)
        print("\nFetching balance...")
        balance = exchange.fetch_balance()
        usdt = balance['total'].get('USDT', 0)
        print(f"USDT Balance: {usdt}")
        
        # 3. Fetch current positions
        print("\nFetching positions...")
        positions = exchange.fetch_positions()
        active_positions = [p for p in positions if float(p['contracts']) > 0]
        for p in active_positions:
            print(f"Position: {p['symbol']} {p['side']} {p['contracts']} @ {p['entryPrice']}")
            
    except Exception as e:
        print(f"\nConnection failed: {e}")

if __name__ == "__main__":
    test_connection()
