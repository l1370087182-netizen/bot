import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

def test():
    exchange = ccxt.binanceusdm({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_API_SECRET'),
        'urls': {
            'api': {
                'public': 'https://fapi.binance.me/fapi',
                'private': 'https://fapi.binance.me/fapi',
            }
        },
        'options': {'defaultMarketType': 'future'},
        'enableRateLimit': True,
    })
    
    print("Testing connection to Binance Futures...")
    try:
        # Try fetching balance directly from fapi
        balance = exchange.fapiPrivateGetAccount()
        print("✅ Successfully fetched account info via direct fapi call")
        usdt_balance = 0
        for asset in balance['assets']:
            if asset['asset'] == 'USDT':
                usdt_balance = asset['walletBalance']
                break
        print(f"USDT Balance: {usdt_balance}")
        
        # Try standard fetch_balance
        print("\nTesting fetch_balance()...")
        std_balance = exchange.fetch_balance({'type': 'future'})
        print(f"✅ Successfully fetched balance via fetch_balance: {std_balance['total']['USDT']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test()
