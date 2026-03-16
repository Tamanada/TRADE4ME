# TRADE4ME - Plan d'Architecture
## Bot de Trading Crypto Scalping en Python

---

## 1. Structure du Projet

```
TRADE4ME/
├── config/
│   ├── settings.yaml          # Configuration générale (exchange, paires, timeframes)
│   └── strategies.yaml        # Paramètres des stratégies
├── src/
│   ├── __init__.py
│   ├── bot.py                 # Moteur principal du bot (boucle de trading)
│   ├── exchange/
│   │   ├── __init__.py
│   │   └── client.py          # Connexion exchange via CCXT (Binance, Bybit, etc.)
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py         # Récupération des données OHLCV en temps réel
│   │   └── orderbook.py       # Lecture du carnet d'ordres (profondeur)
│   ├── indicators/
│   │   ├── __init__.py
│   │   └── technical.py       # Indicateurs techniques (RSI, EMA, MACD, Bollinger)
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py            # Classe abstraite BaseStrategy
│   │   ├── scalp_ema.py       # Stratégie EMA crossover rapide
│   │   ├── scalp_rsi.py       # Stratégie RSI oversold/overbought
│   │   └── scalp_momentum.py  # Stratégie momentum + volume
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── order_manager.py   # Gestion des ordres (market, limit, stop)
│   │   └── position_tracker.py # Suivi des positions ouvertes
│   ├── risk/
│   │   ├── __init__.py
│   │   └── manager.py         # Stop-loss, take-profit, taille de position, drawdown max
│   └── utils/
│       ├── __init__.py
│       ├── logger.py          # Logging structuré (fichier + console)
│       └── notifier.py        # Notifications (console, futur: Telegram/Discord)
├── backtest/
│   ├── __init__.py
│   ├── engine.py              # Moteur de backtesting
│   └── report.py              # Génération de rapports de performance
├── tests/
│   ├── __init__.py
│   ├── test_indicators.py
│   ├── test_strategies.py
│   └── test_risk.py
├── data/                      # Données historiques (CSV) pour backtesting
├── logs/                      # Fichiers de logs
├── .env.example               # Template des variables d'environnement
├── .gitignore
├── requirements.txt
├── README.md
├── main.py                    # Point d'entrée principal
└── backtest_runner.py         # Point d'entrée backtesting
```

---

## 2. Dépendances Principales

| Package       | Usage                                      |
|---------------|---------------------------------------------|
| `ccxt`        | Connexion unifiée aux exchanges crypto      |
| `pandas`      | Manipulation des données OHLCV              |
| `numpy`       | Calculs numériques                          |
| `ta`          | Indicateurs techniques (ta-lib alternative) |
| `pyyaml`      | Parsing des fichiers de config              |
| `python-dotenv`| Variables d'environnement (.env)           |
| `rich`        | Affichage console enrichi (tableaux, logs)  |
| `websockets`  | Flux de données en temps réel (optionnel)   |
| `pytest`      | Tests unitaires                             |

---

## 3. Étapes d'Implémentation (dans l'ordre)

### Phase 1 : Fondations
1. **Setup du projet** - Structure, .gitignore, requirements.txt, config YAML
2. **Exchange client** - Connexion CCXT, récupération des paires, balances
3. **Data fetcher** - Récupération OHLCV (bougies), formatage en DataFrame pandas
4. **Logger** - Système de logging structuré avec Rich

### Phase 2 : Intelligence
5. **Indicateurs techniques** - RSI, EMA (9/21), MACD, Bollinger Bands, Volume
6. **Base Strategy** - Classe abstraite avec interface analyze() → Signal (BUY/SELL/HOLD)
7. **Scalping Strategy #1** - EMA crossover (EMA9 croise EMA21) + filtre RSI + volume
8. **Scalping Strategy #2** - RSI bounce (survente → rebond) avec confirmation volume

### Phase 3 : Exécution
9. **Order Manager** - Passage d'ordres market/limit, annulation, suivi du statut
10. **Position Tracker** - Suivi des positions ouvertes, P&L en temps réel
11. **Risk Manager** - Stop-loss auto, take-profit, taille max de position, drawdown max

### Phase 4 : Boucle Principale
12. **Bot Engine** - Boucle principale : fetch data → analyze → decide → execute → log
13. **Mode Paper Trading** - Simulation sans argent réel (OBLIGATOIRE avant le live)
14. **Configuration YAML** - Paires à trader, timeframes, paramètres de risque

### Phase 5 : Validation
15. **Backtesting Engine** - Tester les stratégies sur données historiques
16. **Rapport de performance** - Win rate, Sharpe ratio, max drawdown, P&L
17. **Tests unitaires** - Coverage des indicateurs, stratégies, risk management

---

## 4. Sécurité & Bonnes Pratiques

- **Clés API dans .env** (jamais commitées)
- **Mode Paper Trading par défaut** - Le bot démarre TOUJOURS en simulation
- **Limites de risque strictes** - Max 2% du capital par trade, drawdown max 10%
- **Logging complet** - Chaque décision et trade est loggé
- **Pas d'accès aux retraits** - Les clés API ne doivent PAS avoir la permission de retrait

---

## 5. Exchange Cible

**Binance** en priorité (le plus liquide pour le scalping crypto), avec possibilité de switcher via CCXT.

---

## 6. Paires de Trading par Défaut

- `BTC/USDT` (la plus liquide)
- `ETH/USDT` (très liquide, bon pour scalp)
- Configurable dans `settings.yaml`
