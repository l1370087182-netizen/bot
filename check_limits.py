import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

def check_limits():
    exchange = ccxt.binanceusdm({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_API_SECRET'),
        'enableRateLimit': True,
        'options': {'adjustForTimeDifference': True}
    })
    
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
    exchange.load_markets()
    
    for symbol in symbols:
        market = exchange.market(symbol)
        print(f"\nLimits for {symbol}:")
        print(f"  Min Amount: {market['limits']['amount']['min']}")
        print(f"  Min Cost (Notional): {market['limits']['cost']['min']} USDT")
        
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        min_notional = market['limits']['cost']['min']
        if min_notional is None:
            # Some markets use 'minNotional' in info
            min_notional = float(market['info'].get('minNotional', 5.0))
            
        print(f"  Current Price: {price}")
        print(f"  Min Notional (from info): {min_notional} USDT")

if __name__ == "__main__":
    check_limits()
