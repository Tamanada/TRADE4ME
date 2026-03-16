# TRADE4ME

Bot de trading crypto scalping en Python.

## Setup

```bash
# Cloner le repo
git clone https://github.com/Tamanada/TRADE4ME.git
cd TRADE4ME

# Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Installer les dépendances
pip install -r requirements.txt

# Configurer les clés API
cp .env.example .env
# Editer .env avec vos clés Binance
```

## Usage

```bash
# Paper trading (simulation - mode par défaut)
python main.py

# Backtesting sur données historiques
python backtest_runner.py --symbol BTC/USDT --timeframe 5m --limit 500

# Live trading (ATTENTION: argent réel!)
python main.py --live
```

## Configuration

- `config/settings.yaml` - Exchange, paires, timeframes, paramètres de risque
- `config/strategies.yaml` - Paramètres des stratégies de scalping

## Stratégies

| Stratégie | Description |
|-----------|-------------|
| **Scalp EMA** | EMA crossover (9/21) + filtre RSI + volume |
| **Scalp RSI** | RSI bounce (survente/surachat) + confirmation EMA |
| **Scalp Momentum** | MACD crossover + Bollinger Bands + volume |

## Avertissement

Le trading comporte des risques de perte financière. Ce bot est un outil technique - les décisions d'investissement restent votre responsabilité. Commencez TOUJOURS en mode paper trading.
