import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Configuration
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')

# Validate API keys are set
if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env file")

# Trading Parameters - All Binance USDT-Margined Futures (excluding BTC)
SYMBOLS = [
    'ETH/USDT:USDT',      # Ethereum
    'BNB/USDT:USDT',      # Binance Coin
    'SOL/USDT:USDT',      # Solana
    'XRP/USDT:USDT',      # Ripple
    'DOGE/USDT:USDT',     # Dogecoin
    'ADA/USDT:USDT',      # Cardano
    'AVAX/USDT:USDT',     # Avalanche
    'DOT/USDT:USDT',      # Polkadot
    'LINK/USDT:USDT',     # Chainlink
    'MATIC/USDT:USDT',    # Polygon
    'LTC/USDT:USDT',      # Litecoin
    'BCH/USDT:USDT',      # Bitcoin Cash
    'UNI/USDT:USDT',      # Uniswap
    'ATOM/USDT:USDT',     # Cosmos
    'ETC/USDT:USDT',      # Ethereum Classic
    'XLM/USDT:USDT',      # Stellar
    'NEAR/USDT:USDT',     # NEAR Protocol
    'ALGO/USDT:USDT',     # Algorand
    'VET/USDT:USDT',      # VeChain
    'FIL/USDT:USDT',      # Filecoin
    'ICP/USDT:USDT',      # Internet Computer
    'TRX/USDT:USDT',      # TRON
    'APT/USDT:USDT',      # Aptos
    'ARB/USDT:USDT',      # Arbitrum
    'OP/USDT:USDT',       # Optimism
    'SAND/USDT:USDT',     # The Sandbox
    'MANA/USDT:USDT',     # Decentraland
    'AXS/USDT:USDT',      # Axie Infinity
    'AAVE/USDT:USDT',     # Aave
    'SUSHI/USDT:USDT',    # SushiSwap
    'CRV/USDT:USDT',      # Curve DAO
    'SNX/USDT:USDT',      # Synthetix
    'MKR/USDT:USDT',      # Maker
    'COMP/USDT:USDT',     # Compound
    'YFI/USDT:USDT',      # Yearn.finance
    '1INCH/USDT:USDT',    # 1inch
    'GRT/USDT:USDT',      # The Graph
    'ENJ/USDT:USDT',      # Enjin Coin
    'CHZ/USDT:USDT',      # Chiliz
    'BAT/USDT:USDT',      # Basic Attention Token
    'ZEC/USDT:USDT',      # Zcash
    'XMR/USDT:USDT',      # Monero
    'DASH/USDT:USDT',     # Dash
    'NEO/USDT:USDT',      # NEO
    'QTUM/USDT:USDT',     # Qtum
    'ONT/USDT:USDT',      # Ontology
    'ZIL/USDT:USDT',      # Zilliqa
    'ZRX/USDT:USDT',      # 0x
    'KNC/USDT:USDT',      # Kyber Network
    'LRC/USDT:USDT',      # Loopring
    'BAND/USDT:USDT',     # Band Protocol
    'RLC/USDT:USDT',      # iExec RLC
    'STORJ/USDT:USDT',    # Storj
    'BLZ/USDT:USDT',      # Bluzelle
    'KAVA/USDT:USDT',     # Kava
    'RUNE/USDT:USDT',     # THORChain
    'SFP/USDT:USDT',      # SafePal
    'CAKE/USDT:USDT',     # PancakeSwap
    'BAKE/USDT:USDT',     # BakeryToken
    'BURGER/USDT:USDT',   # Burger Swap
    'UNFI/USDT:USDT',     # Unifi Protocol DAO
    'LIT/USDT:USDT',      # Litentry
    'DODO/USDT:USDT',     # DODO
    'REEF/USDT:USDT',     # Reef Finance
    'CHR/USDT:USDT',      # Chromia
    'ALICE/USDT:USDT',    # MyNeighborAlice
    'FORTH/USDT:USDT',    # Ampleforth Governance Token
    'GTC/USDT:USDT',      # Gitcoin
    'TLM/USDT:USDT',      # Alien Worlds
    'SLP/USDT:USDT',      # Smooth Love Potion
    'COTI/USDT:USDT',     # COTI
    'KEEP/USDT:USDT',     # Keep Network
    'NU/USDT:USDT',       # NuCypher
    'CELR/USDT:USDT',     # Celer Network
    'ANKR/USDT:USDT',     # Ankr
    'HOT/USDT:USDT',      # Holo
    'IOST/USDT:USDT',     # IOST
    'DENT/USDT:USDT',     # Dent
    'MFT/USDT:USDT',      # Mainframe
    'CVC/USDT:USDT',      # Civic
    'STMX/USDT:USDT',     # StormX
    'TROY/USDT:USDT',     # TROY
    'FTM/USDT:USDT',      # Fantom
    'THETA/USDT:USDT',    # Theta Network
    'EGLD/USDT:USDT',     # MultiversX (Elrond)
    'HBAR/USDT:USDT',     # Hedera
    'FLOW/USDT:USDT',     # Flow
    'GALA/USDT:USDT',     # Gala
    'IMX/USDT:USDT',      # Immutable X
    'APE/USDT:USDT',      # ApeCoin
    'GMT/USDT:USDT',      # STEPN
    'JASMY/USDT:USDT',    # JasmyCoin
    'ZEN/USDT:USDT',      # Horizen
    'SKL/USDT:USDT',      # SKALE Network
    'LPT/USDT:USDT',      # Livepeer
    'API3/USDT:USDT',     # API3
    'AUDIO/USDT:USDT',    # Audius
    'RAY/USDT:USDT',      # Raydium
    'C98/USDT:USDT',      # Coin98
    'MASK/USDT:USDT',     # Mask Network
    'DYDX/USDT:USDT',     # dYdX
    'ENS/USDT:USDT',      # Ethereum Name Service
    'PEOPLE/USDT:USDT',   # ConstitutionDAO
    'RNDR/USDT:USDT',     # Render Token
    'INJ/USDT:USDT',      # Injective
    'FET/USDT:USDT',      # Fetch.ai
    'AGIX/USDT:USDT',     # SingularityNET
    'OCEAN/USDT:USDT',    # Ocean Protocol
    'ROSE/USDT:USDT',     # Oasis Network
    'IOTX/USDT:USDT',     # IoTeX
    'CELO/USDT:USDT',     # Celo
    'ONE/USDT:USDT',      # Harmony
    'SRM/USDT:USDT',      # Serum
    'COCOS/USDT:USDT',    # Cocos-BCX
    'ALPHA/USDT:USDT',    # Alpha Finance Lab
    'BEL/USDT:USDT',      # Bella Protocol
    'DGB/USDT:USDT',      # DigiByte
    'NKN/USDT:USDT',      # NKN
    'SC/USDT:USDT',       # Siacoin
    'DCR/USDT:USDT',      # Decred
    'XEM/USDT:USDT',      # NEM
    'QTUM/USDT:USDT',     # Qtum
    'ICX/USDT:USDT',      # ICON
    'WAVES/USDT:USDT',    # Waves
    'OMG/USDT:USDT',      # OMG Network
    'NANO/USDT:USDT',     # Nano
    'BTS/USDT:USDT',      # BitShares
    'LSK/USDT:USDT',      # Lisk
    'PAXG/USDT:USDT',     # PAX Gold
    'TUSD/USDT:USDT',     # TrueUSD
    'USDC/USDT:USDT',     # USD Coin (作为交易对，不是稳定币存储)
]
TIMEFRAME = '30m'
LEVERAGE = 10  # 开启 10 倍杠杆
POSITION_SIZE_PCT = 0.9
MIN_ORDER_VALUE_USDT = 1.0

# Risk Management
MAX_DAILY_LOSS_PCT = 0.10  # 10% daily drawdown limit
STOP_LOSS_PCT = 0.02       # 2% hard stop loss per trade
TAKE_PROFIT_PCT = 0.04     # 4% take profit per trade
SLIPPAGE_PROTECTION = 0.001 # 0.1% max slippage allowed

# Bot Settings
LOOP_INTERVAL = 60  # Check every 60 seconds
TIME_SYNC_INTERVAL = 10  # Re-sync time every N cycles
