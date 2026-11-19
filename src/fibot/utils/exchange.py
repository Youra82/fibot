# src/fibot/utils/exchange.py
# KORRIGIERTE VERSION (BASIEREND AUF JAEGERBOT/TITANBOT-LOGIK)
import ccxt
import pandas as pd
from datetime import datetime, timezone
import logging
import time # Hinzugefügt für fetch_recent_ohlcv
from typing import Optional, Dict, List, Any 
import os
import json
from contextlib import contextmanager
import sys 

# Pfad Setup für utils Import (ggf. anpassen)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

logger = logging.getLogger(__name__)

class Exchange:
    def __init__(self, account_config):
        self.account = account_config
        self.exchange = getattr(ccxt, 'bitget')({
            'apiKey': self.account.get('apiKey'),
            'secret': self.account.get('secret'),
            'password': self.account.get('password'),
            'options': {
                'defaultType': 'swap', 
            },
            'enableRateLimit': True, 
        })

        try:
            self.markets = self.exchange.load_markets()
            logger.info("Märkte erfolgreich geladen.")
        except Exception as e:
            logger.critical(f"Konnte Märkte nicht laden! API-Keys oder Verbindung prüfen. Fehler: {e}")
            self.markets = {} 

    # --- OHLCV Methoden ---
    def fetch_recent_ohlcv(self, symbol, timeframe, limit=1000):
        if not self.markets: return pd.DataFrame() 
        if not self.exchange.has['fetchOHLCV']:
            raise ccxt.NotSupported("fetchOHLCV not supported by the exchange.")

        timeframe_duration_in_ms = self.exchange.parse_timeframe(timeframe) * 1000
        since = self.exchange.milliseconds() - timeframe_duration_in_ms * limit
        all_ohlcv = []
        fetch_limit = 200
        last_ts = None
        net_retries = 0

        # Ueberlappend paginieren (naechste Seite ab der letzten erhaltenen Kerze):
        # mit "letzte + tf" verlor Bitget an der Seitengrenze JEDES Mal genau eine
        # Kerze (30.09.2026: 499 statt 500, bei allen Symbolen/Timeframes) -- das
        # Live-Signal lief damit auf einem Fenster mit Loch, anders als der Backtest.
        while since < self.exchange.milliseconds():
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since, fetch_limit)
            except ccxt.NetworkError as e:   # inkl. 429 / RateLimitExceeded
                net_retries += 1
                if net_retries > 5:
                    logger.error(f"OHLCV {symbol} ({timeframe}): {e} — gebe auf.")
                    return pd.DataFrame()
                logger.warning(f"OHLCV {symbol} ({timeframe}): {type(e).__name__} — Retry {net_retries}/5")
                time.sleep(2 * net_retries)
                continue
            except Exception as e:
                logger.error(f"Error fetching OHLCV chunk for {symbol}: {e}")
                return pd.DataFrame()
            ohlcv = [c for c in ohlcv if last_ts is None or c[0] > last_ts]
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            last_ts = ohlcv[-1][0]
            since = last_ts

        if not all_ohlcv:
            logger.warning(f"No OHLCV data fetched for {symbol} ({timeframe}).")
            return pd.DataFrame()

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep='last')]

        if len(df) > limit:
            df = df.iloc[-limit:]

        # Nur warnen: fehlt eine Kerze auch bei Bitget selbst (Wartung), hat der
        # Backtest dieselbe Luecke -- Aussetzen wuerde den Handel ueber die ganze
        # Fensterlaenge blockieren.
        gaps = df.index.to_series().diff().dropna()
        n_gaps = int((gaps != pd.Timedelta(milliseconds=timeframe_duration_in_ms)).sum())
        if n_gaps:
            logger.warning(f"OHLCV {symbol} ({timeframe}): {n_gaps} Lücke(n) in den Kerzen.")

        return df


    def fetch_historical_ohlcv(self, symbol, timeframe, start_date_str, end_date_str):
        if not self.markets: return pd.DataFrame() 
        if not self.exchange.has['fetchOHLCV']:
            raise ccxt.NotSupported("fetchOHLCV not supported by the exchange.")

        start_ts = int(self.exchange.parse8601(start_date_str + 'T00:00:00Z'))
        end_ts = int(self.exchange.parse8601(end_date_str + 'T23:59:59Z'))
        timeframe_duration_in_ms = self.exchange.parse_timeframe(timeframe) * 1000
        all_ohlcv = []
        fetch_limit = 200
        current_ts = start_ts
        logger.info(f"Starte historischen Download für {symbol} ({timeframe}) von {start_date_str} bis {end_date_str}")

        while current_ts < end_ts:
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, current_ts, fetch_limit)
                if not ohlcv: break
                ohlcv = [candle for candle in ohlcv if candle[0] <= end_ts]
                if not ohlcv: break
                all_ohlcv.extend(ohlcv)
                current_ts = ohlcv[-1][0] + timeframe_duration_in_ms
                last_date = pd.to_datetime(ohlcv[-1][0], unit='ms', utc=True).strftime('%Y-%m-%d')
                logger.debug(f"Daten bis {last_date} heruntergeladen...")
                time.sleep(self.exchange.rateLimit / 1000)
            except ccxt.RateLimitExceeded as e:
                logger.warning(f"Rate limit exceeded during historical fetch: {e}. Waiting...")
                time.sleep(10)
            except Exception as e:
                logger.error(f"Error fetching historical OHLCV chunk: {e}")
                time.sleep(5)

        if not all_ohlcv:
            logger.warning(f"Keine historischen OHLCV-Daten für {symbol} im Zeitraum gefunden.")
            return pd.DataFrame()

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        df = df[(df.index >= pd.to_datetime(start_date_str, utc=True)) & (df.index <= pd.to_datetime(end_date_str + 'T23:59:59Z', utc=True))]

        logger.info(f"Daten geladen: {symbol} ({timeframe}) | {start_date_str} → {end_date_str} | {len(df)} Kerzen")
        return df

    # --- Getter Methoden ---
    def fetch_ticker(self, symbol):
        if not self.markets: return None 
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Tickers für {symbol}: {e}")
            raise e

    def fetch_min_amount_tradable(self, symbol: str) -> float:
        if not self.markets: return 0.0 
        try:
            if symbol not in self.markets:
                logger.warning(f"Markt {symbol} nicht gefunden. Lade erneut...")
                self.markets = self.exchange.load_markets()
                if symbol not in self.markets:
                    logger.error(f"Markt {symbol} konnte auch nach erneutem Laden nicht gefunden werden.")
                    return 0.0

            min_amount = self.markets[symbol].get('limits', {}).get('amount', {}).get('min')
            if min_amount is None:
                logger.warning(f"Minimale Handelsmenge für {symbol} nicht gefunden. Verwende Fallback 0.0")
                return 0.0
            return float(min_amount)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der minimalen Handelsmenge für {symbol}: {e}")
            return 0.0


    def amount_to_precision(self, symbol: str, amount: float) -> str:
        if not self.markets: return str(amount) 
        try:
            return self.exchange.amount_to_precision(symbol, amount)
        except Exception as e:
            logger.error(f"Fehler beim Konvertieren der Menge {amount} für {symbol}: {e}")
            return str(amount)


    def price_to_precision(self, symbol: str, price: float) -> str:
        if not self.markets: return str(price) 
        try:
            return self.exchange.price_to_precision(symbol, price)
        except Exception as e:
            logger.error(f"Fehler beim Konvertieren des Preises {price} für {symbol}: {e}")
            return str(price)

    def fetch_balance_usdt(self):
        if not self.markets: return 0.0
        try:
            params = {'marginCoin': 'USDT', 'productType': 'USDT-FUTURES'} # productType hinzugefügt
            balance = self.exchange.fetch_balance(params=params)
            usdt_balance = 0.0

            # Verschiedene Strukturen prüfen
            if 'USDT' in balance and 'free' in balance['USDT'] and balance['USDT']['free'] is not None:
                 usdt_balance = float(balance['USDT']['free'])
            elif 'info' in balance and isinstance(balance['info'], list):
                for asset_info in balance['info']:
                    if asset_info.get('marginCoin') == 'USDT':
                        usdt_balance = float(asset_info.get('available', 0.0))
                        break
            elif 'info' in balance and isinstance(balance['info'], dict) and 'USDT' in balance['info']:
                 usdt_balance = float(balance['info']['USDT'].get('available', 0.0))
            
            # Fallback auf 'equity' wenn 'available' fehlt (kann bei Unified Accounts vorkommen)
            if usdt_balance == 0.0 and 'info' in balance and isinstance(balance['info'], list):
                 for asset_info in balance['info']:
                    if asset_info.get('marginCoin') == 'USDT' and 'equity' in asset_info:
                        usdt_balance = float(asset_info.get('equity', 0.0))
                        logger.debug("Verwende 'equity' als Fallback für Kontostand.")
                        break

            # Fallback auf total, wenn free/available/equity nicht gefunden
            if usdt_balance == 0.0 and 'total' in balance and 'USDT' in balance['total']:
                usdt_balance = float(balance['total']['USDT'])
                logger.debug("Verwende 'total' als Fallback für Kontostand.")

            logger.info(f"Verfügbares USDT-Guthaben: {usdt_balance:.2f}")
            return usdt_balance

        except ccxt.AuthenticationError as e:
            logger.critical(f"Authentifizierungsfehler beim Abrufen des Kontostands: {e}. API-Keys prüfen!")
            return 0.0
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Kontostands: {e}", exc_info=True)
            return 0.0

    # --- Order & Positions Management Methoden ---

    def fetch_order(self, id: str, symbol: str):
        if not self.markets: return None
        try:
            params = {'productType': 'USDT-FUTURES'}
            return self.exchange.fetch_order(id, symbol, params=params)
        except ccxt.OrderNotFound:
            logger.warning(f"Order {id} für {symbol} nicht gefunden.")
            return None
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Order {id} für {symbol}: {e}")
            raise e

    def fetch_open_orders(self, symbol: str, strict: bool = False):
        if not self.markets:
            if strict:
                raise RuntimeError("Markets nicht geladen -- offener Orderstatus unbekannt")
            return []
        try:
            params = {'stop': False, 'productType': 'USDT-FUTURES'}
            return self.exchange.fetch_open_orders(symbol, params=params)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen offener Orders für {symbol}: {e}")
            if strict:
                raise
            return []

    def fetch_open_trigger_orders(self, symbol: str, strict: bool = False):
        if not self.markets:
            if strict:
                raise RuntimeError("Markets nicht geladen -- Trigger-Orderstatus unbekannt")
            return []
        try:
            params = {'stop': True, 'productType': 'USDT-FUTURES'}
            return self.exchange.fetch_open_orders(symbol, params=params)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen offener Trigger-Orders für {symbol}: {e}")
            if strict:
                raise
            return []

    def fetch_position_tpsl_orders(self, symbol: str, strict: bool = False):
        """Position-TP/SL (planType 'profit_loss'), z.B. die an eine Limit-Entry
        gehaengten preset-SL/TP. Tauchen in fetch_open_trigger_orders() NICHT auf
        (das liefert nur 'normal_plan') -- Muster aus ltbbot."""
        if not self.markets:
            if strict:
                raise RuntimeError("Markets nicht geladen -- Position-TP/SL-Status unbekannt")
            return []
        try:
            params = {'stop': True, 'planType': 'profit_loss', 'productType': 'USDT-FUTURES'}
            return self.exchange.fetch_open_orders(symbol, params=params)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Position-TP/SL-Orders für {symbol}: {e}")
            if strict:
                raise
            return []

    def fetch_closed_trigger_orders(self, symbol: str, limit: int = 20):
        if not self.markets: return []
        try:
            closed_triggers = []
            params = {'stop': True, 'productType': 'USDT-FUTURES'} 
            if self.exchange.has['fetchOrders']:
                all_orders = self.exchange.fetchOrders(symbol, limit=limit*3, params=params)
                closed_triggers = [o for o in all_orders if o.get('stopPrice') is not None and o.get('status') in ['closed', 'canceled']]
            else:
                 logger.warning("fetchOrders wird nicht unterstützt, um geschlossene Trigger zu prüfen.")
                 return []

            closed_triggers.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return closed_triggers[:limit]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen geschlossener Trigger-Orders für {symbol}: {e}")
            return []


    def cancel_order(self, id: str, symbol: str):
        if not self.markets: return None
        try:
            params = {'stop': False, 'productType': 'USDT-FUTURES'}
            return self.exchange.cancel_order(id, symbol, params=params)
        except ccxt.OrderNotFound:
            logger.debug(f"Normale Order {id} für {symbol} beim Stornieren nicht gefunden.")
            return None
        except Exception as e:
            logger.error(f"Fehler beim Stornieren der normalen Order {id} für {symbol}: {e}")
            raise e


    def cancel_trigger_order(self, id: str, symbol: str):
        if not self.markets: return None
        try:
            params = {'stop': True, 'productType': 'USDT-FUTURES'}
            return self.exchange.cancel_order(id, symbol, params=params)
        except ccxt.OrderNotFound:
            logger.debug(f"Trigger Order {id} für {symbol} beim Stornieren nicht gefunden.")
            return None
        except Exception as e:
            logger.error(f"Fehler beim Stornieren der Trigger Order {id} für {symbol}: {e}")
            raise e
            
    def cancel_stale_entry_orders(self, keep_symbols):
        """Kontoweit: Entry-Limit-Orders (tradeSide 'open') auf Symbolen stornieren, die NICHT in
        keep_symbols (active_strategies) stehen. Nach einem Portfolio-Wechsel laeuft fuer diese Symbole
        kein Prozess mehr, der ihre Orders je Kerze nachzieht/storniert -- sie blieben liegen und
        konnten spaeter ungesteuert gefuellt werden (DOGE 2026-10-16/17; ltbbot-Muster 8dfd057).
        TP/SL (tradeSide 'close') bleiben. Rueckgabe: Liste (symbol, orderId) der stornierten Orders."""
        if not self.markets: return []
        by_id = {m.get('id'): s for s, m in self.markets.items() if m.get('swap')}
        resp = self.exchange.private_mix_get_v2_mix_order_orders_pending({'productType': 'USDT-FUTURES'})
        cancelled = []
        for o in (resp.get('data') or {}).get('entrustedList') or []:
            sym = by_id.get(o.get('symbol'))
            if o.get('tradeSide') != 'open' or not sym or sym in keep_symbols:
                continue
            self.cancel_order(o['orderId'], sym)
            cancelled.append((sym, o['orderId']))
        return cancelled

    def cancel_all_orders_for_symbol(self, symbol, strict: bool = False):
        """Storniert alle offenen Orders (normal und trigger) für ein Symbol."""
        if not self.markets: return 0
        cancelled_count = 0

        # 1. Normale Orders stornieren (stop: False)
        try:
            logger.info(f"Sende Befehl 'cancelAllOrders' (Normal) für {symbol}...")
            self.exchange.cancel_all_orders(symbol, params={'productType': 'USDT-FUTURES', 'stop': False})
            cancelled_count += 1
            time.sleep(0.5) 
        except ccxt.ExchangeError as e:
            if 'Order not found' in str(e) or 'no order to cancel' in str(e).lower() or '22001' in str(e):
                logger.info("Keine normalen Orders zum Stornieren gefunden.")
            else:
                logger.error(f"Fehler beim Stornieren normaler Orders: {e}")
                if strict:
                    raise
        except Exception as e:
            logger.error(f"Unerwarteter Fehler beim Stornieren normaler Orders: {e}")
            if strict:
                raise

        # 2. Trigger Orders stornieren (stop: True)
        try:
            logger.info(f"Sende Befehl 'cancelAllOrders' (Trigger/Stop) für {symbol}...")
            self.exchange.cancel_all_orders(symbol, params={'productType': 'USDT-FUTURES', 'stop': True})
            cancelled_count += 1
            time.sleep(0.5)
        except ccxt.ExchangeError as e:
            if 'Order not found' in str(e) or 'no order to cancel' in str(e).lower() or '22001' in str(e):
                logger.info("Keine Trigger-Orders zum Stornieren gefunden.")
            else:
                logger.error(f"Fehler beim Stornieren von Trigger-Orders: {e}")
                if strict:
                    raise
        except Exception as e:
            logger.error(f"Unerwarteter Fehler beim Stornieren von Trigger-Orders: {e}")
            if strict:
                raise

        return cancelled_count


    def fetch_open_positions(self, symbol, strict: bool = False):
        """strict=True: API-Fehler werden weitergereicht statt als 'keine Position' ([]) gemeldet."""
        if not self.markets:
            if strict:
                raise RuntimeError("Markets nicht geladen -- Positionsstatus unbekannt")
            return []
        try:
            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
            positions = self.exchange.fetch_positions([symbol], params=params)
            open_positions = []
            for p in positions:
                 try:
                     size_key = 'contracts' if 'contracts' in p else 'contractSize'
                     contracts_str = p.get(size_key)
                     if contracts_str is not None and abs(float(contracts_str)) > 1e-9:
                          open_positions.append(p)
                     elif p.get('initialMargin', 0) > 0 or p.get('maintMargin', 0) > 0:
                         if contracts_str is None or abs(float(contracts_str)) <= 1e-9 :
                              logger.warning(f"Position für {symbol} hat Margin > 0 aber Size ≈ 0. Betrachte sie als offen. Details: {p}")
                         open_positions.append(p)
                     elif contracts_str is None and strict:
                          raise RuntimeError(f"Positionsgroesse fuer {symbol} fehlt")
                 except (ValueError, TypeError, KeyError) as e:
                     logger.warning(f"Konnte Positionsgröße nicht prüfen: {e}. Positionsdaten: {p}")
                     if strict:
                         raise RuntimeError(f"Positionsdaten fuer {symbol} nicht interpretierbar: {e}") from e
                     continue
            return open_positions
        except Exception as e:
            logger.error(f"Fehler beim Abrufen offener Positionen für {symbol}: {e}", exc_info=True)
            if strict:
                raise
            return []


    def close_position(self, symbol: str, side: Optional[str] = None):
        if not self.markets: return None
        try:
            position_list = self.fetch_open_positions(symbol)
            if not position_list:
                logger.warning(f"Keine offene Position zum Schließen für {symbol} gefunden.")
                return None
            position = position_list[0]
            close_side = 'sell' if position['side'] == 'long' else 'buy'
            size_key = 'contracts' if 'contracts' in position else 'contractSize'
            amount = position.get(size_key)
            if amount is None:
                 logger.error(f"Konnte Positionsgröße ('{size_key}') nicht aus Positionsdaten lesen: {position}")
                 return None
            logger.info(f"Schließe {position['side']} Position für {symbol} mit Market Order (Menge: {amount}).")
            return self.place_market_order(symbol, close_side, float(amount), reduce=True)
        except Exception as e:
            logger.error(f"Fehler beim Schließen der Position für {symbol}: {e}")
            raise e


    def set_margin_mode(self, symbol, margin_mode='isolated'):
        if not self.markets: return
        margin_mode_lower = margin_mode.lower()
        if margin_mode_lower not in ['isolated', 'cross']:
            logger.error(f"Ungültiger Margin-Modus: {margin_mode}.")
            return
        try:
            params={'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
            self.exchange.set_margin_mode(margin_mode_lower, symbol, params=params)
            logger.info(f"Margin-Modus für {symbol} auf '{margin_mode_lower}' gesetzt.")
        except ccxt.ExchangeError as e:
            if 'Margin mode is the same' in str(e) or 'margin mode is not changed' in str(e).lower() or '40051' in str(e):
                logger.debug(f"Margin-Modus für {symbol} ist bereits '{margin_mode_lower}'.")
            else:
                logger.error(f"Fehler beim Setzen des Margin-Modus für {symbol}: {e}")
        except Exception as e:
            logger.error(f"Unerwarteter Fehler beim Setzen des Margin-Modus für {symbol}: {e}")

    def set_leverage(self, symbol, leverage, margin_mode='isolated'):
        if not self.markets: return
        try:
            leverage = int(leverage)
            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}

            if margin_mode.lower() == 'isolated':
                params_long = {**params, 'holdSide': 'long'}
                self.exchange.set_leverage(leverage, symbol, params=params_long)
                logger.debug(f"Isolated Leverage für {symbol} (Long) auf {leverage}x gesetzt.")
                time.sleep(0.2)
                params_short = {**params, 'holdSide': 'short'}
                self.exchange.set_leverage(leverage, symbol, params=params_short)
                logger.debug(f"Isolated Leverage für {symbol} (Short) auf {leverage}x gesetzt.")
            else: 
                self.exchange.set_leverage(leverage, symbol, params=params)
                logger.debug(f"Cross Leverage für {symbol} auf {leverage}x gesetzt.")
            logger.info(f"Hebel für {symbol} ({margin_mode}) auf {leverage}x gesetzt.")
        except ccxt.ExchangeError as e:
            if 'Leverage not changed' in str(e) or 'leverage is not modified' in str(e).lower() or '40052' in str(e):
                logger.debug(f"Hebel für {symbol} ist bereits {leverage}x.")
            else:
                logger.error(f"Fehler beim Setzen des Hebels für {symbol}: {e}")
        except Exception as e:
            logger.error(f"Unerwarteter Fehler beim Setzen des Hebels für {symbol}: {e}")

    # --- Order Platzierungs Methoden ---

    def place_market_order(self, symbol: str, side: str, amount: float, reduce: bool = False, params={}):
        if not self.markets: return None
        try:
            order_params = {'reduceOnly': reduce, 'hedged': True, 'marginMode': 'isolated', **params}
            if 'productType' not in order_params:
                order_params['productType'] = 'USDT-FUTURES'
            amount_str = self.amount_to_precision(symbol, amount)
            logger.info(f"Platziere Market Order: {side.upper()} {amount_str} {symbol} (Params: {order_params})")
            return self.exchange.create_order(symbol, 'market', side, float(amount_str), params=order_params)
        except ccxt.InsufficientFunds as e:
            logger.error(f"Nicht genügend Guthaben für Market Order {side} {amount} {symbol}: {e}")
            raise e
        except Exception as e:
            logger.error(f"Fehler beim Platzieren der Market Order für {symbol}: {e}", exc_info=True)
            raise e

    def place_limit_order(self, symbol: str, side: str, amount: float, price: float, reduce: bool = False, params={}):
        if not self.markets: return None
        try:
            order_params = {'reduceOnly': reduce, 'hedged': True, 'marginMode': 'isolated', **params}
            if 'productType' not in order_params:
                order_params['productType'] = 'USDT-FUTURES'
            amount_str = self.amount_to_precision(symbol, amount)
            price_str = self.price_to_precision(symbol, price)
            logger.info(f"Platziere Limit Order: {side.upper()} {amount_str} {symbol} @ {price_str} (Params: {order_params})")
            return self.exchange.create_order(symbol, 'limit', side, float(amount_str), float(price_str), params=order_params)
        except Exception as e:
            logger.error(f"Fehler beim Platzieren der Limit Order für {symbol}: {e}", exc_info=True)
            raise e

    # =========================================================================
    # HIER IST DIE KORREKTUR FÜR TRIGGER MARKET ORDERS (TP/SL)
    # WIR KOPIEREN DIE LOGIK VON JAEGERBOT/TITANBOT
    # =========================================================================
    def place_limit_order_with_tpsl(self, symbol: str, side: str, amount: float, price: float,
                                    sl_price: float, tp_price: float, client_oid: str = None):
        """Limit-Entry mit angehaengtem SL/TP (Bitget presetStopLossPrice/presetStopSurplusPrice).
        Bitget legt beide erst beim Fill als Position-TP/SL an -- die Position ist damit
        ab der ersten Sekunde geschuetzt, auch wenn der Fill zwischen zwei Cron-Laeufen passiert."""
        if not self.markets: return None
        amount_str = self.amount_to_precision(symbol, amount)
        price_str = self.price_to_precision(symbol, price)
        from fibot.utils.execution_guard import validate_bracket
        rounded_sl = float(self.price_to_precision(symbol, sl_price))
        rounded_tp = float(self.price_to_precision(symbol, tp_price))
        tick_size = (self.markets.get(symbol, {}).get('precision', {}) or {}).get('price')
        try:
            tick_size = float(tick_size)
            if not (0 < tick_size < float(price_str)):
                tick_size = None
        except (TypeError, ValueError):
            tick_size = None
        validate_bracket(side, float(price_str), rounded_sl, rounded_tp,
                         self.fetch_ticker(symbol), tick_size=tick_size)
        order_params = {
            'hedged': True, 'marginMode': 'isolated', 'productType': 'USDT-FUTURES',
            'stopLoss':   {'triggerPrice': rounded_sl, 'type': 'market'},
            'takeProfit': {'triggerPrice': rounded_tp, 'type': 'market'},
        }
        if client_oid:
            order_params['clientOid'] = client_oid
        logger.info(f"Platziere Limit+TP/SL: {side.upper()} {amount_str} {symbol} @ {price_str} | SL {sl_price} | TP {tp_price}")
        return self.exchange.create_order(symbol, 'limit', side, float(amount_str), float(price_str), params=order_params)

    def fetch_order_by_client_oid(self, client_oid: str, symbol: str):
        """Resolve an uncertain placement without ever submitting a second order."""
        if not self.markets:
            raise RuntimeError("Markets nicht geladen -- Orderstatus unbekannt")
        if not client_oid:
            raise ValueError("clientOid fehlt")
        try:
            params = {'productType': 'USDT-FUTURES', 'clientOid': client_oid}
            return self.exchange.fetch_order(None, symbol, params=params)
        except ccxt.OrderNotFound:
            logger.warning(f"Order mit clientOid {client_oid} fuer {symbol} nicht gefunden.")
            return None
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von clientOid {client_oid} fuer {symbol}: {e}")
            raise

    def fetch_equity_usdt(self) -> float:
        """Gesamtkapital (USDT total inkl. gebundener Margin) -- Basis fuer risikobasiertes Sizing."""
        if not self.markets: return 0.0
        try:
            bal = self.exchange.fetch_balance(params={'marginCoin': 'USDT', 'productType': 'USDT-FUTURES'})
            return float((bal.get('USDT') or {}).get('total') or 0.0)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Gesamtkapitals: {e}")
            return 0.0

    def place_trigger_market_order(self, symbol: str, side: str, amount: float, trigger_price: float, reduce: bool = False, params={}):
        """Platziert eine Trigger-Market Order (Stop Market oder Take Profit Market)."""
        if not self.markets: return None
        try:
            amount_str = self.amount_to_precision(symbol, amount)
            trigger_price_str = self.price_to_precision(symbol, trigger_price)

            # *** KORREKTUR: Vereinfachte Params, basierend auf JaegerBot/TitanBot ***
            # Wir übergeben NUR 'triggerPrice' und 'reduceOnly'. 
            # ccxt wandelt 'triggerPrice' intern in 'stopPrice' um.
            # KEIN 'planType' oder 'triggerType' hier!
            order_params = {
                'triggerPrice': trigger_price_str,
                'reduceOnly': reduce,
                'hedged': True,
                'marginMode': 'isolated',
                **params
            }
            
            # Stelle sicher, dass productType für Bitget vorhanden ist
            if 'productType' not in order_params:
                 order_params['productType'] = 'USDT-FUTURES'

            logger.info(f"Platziere Trigger Market Order: {side.upper()} {amount_str} {symbol}, Params: {order_params}")
            order = self.exchange.create_order(symbol, 'market', side, float(amount_str), params=order_params)
            return order

        except ccxt.ExchangeError as e:
            logger.error(f"Börsenfehler beim Platzieren der Trigger Market Order für {symbol}: {e}", exc_info=True)
            raise e
        except Exception as e:
            logger.error(f"Allgemeiner Fehler beim Platzieren der Trigger Market Order für {symbol}: {e}", exc_info=True)
            raise e

    # =========================================================================
    # HIER IST DIE KORREKTUR FÜR TRIGGER LIMIT ORDERS (ENTRY)
    # =========================================================================
    def place_trigger_limit_order(self, symbol: str, side: str, amount: float, trigger_price: float, price: float, reduce: bool = False, params={}):
        """Platziert eine Trigger-Limit Order."""
        if not self.markets: return None
        try:
            amount_str = self.amount_to_precision(symbol, amount)
            trigger_price_str = self.price_to_precision(symbol, trigger_price)
            price_str = self.price_to_precision(symbol, price) # Limit Preis nach Trigger

            # *** KORREKTUR: Dieselbe vereinfachte Logik ***
            # Wir übergeben NUR 'triggerPrice' und 'reduceOnly'.
            # Der Unterschied ist, dass der 'type' in create_order 'limit' ist.
            order_params = {
                'triggerPrice': trigger_price_str,
                'reduceOnly': reduce,
                **params
            }
            
            if 'productType' not in order_params:
                 order_params['productType'] = 'USDT-FUTURES'

            logger.info(f"Platziere Trigger Limit Order: {side.upper()} {amount_str} {symbol}, Params: {order_params}, Limit: {price_str}")
            order = self.exchange.create_order(symbol, 'limit', side, float(amount_str), float(price_str), params=order_params)
            return order
        except Exception as e:
            logger.error(f"Fehler beim Platzieren der Trigger Limit Order für {symbol}: {e}", exc_info=True)
            raise e

    # --- Implizite Methoden (Trailing Stop) ---
    # Diese Funktion wird vom ltbtbot nicht verwendet, aber wir lassen sie drin,
    # da sie im Original-Code war (und von Jaeger/Titan kopiert wurde).
    def place_trailing_stop_order(self, symbol, side, amount, activation_price, callback_rate_decimal, params={}):
        if not self.markets: return None
        try:
            market_id = self.exchange.market(symbol)['id']
            margin_coin = 'USDT'

            if side.lower() == 'sell': api_side = 'close_long'
            elif side.lower() == 'buy': api_side = 'close_short'
            else: raise ValueError(f"Ungültiger 'side' für Trailing Stop: {side}")

            api_callback_rate_str = str(callback_rate_decimal * 100.0)

            # Diese Params SIND korrekt für TSL (planType='trailing_stop')
            api_params = {
                'symbol': market_id,
                'marginCoin': margin_coin,
                'planType': 'trailing_stop', 
                'side': api_side,
                'size': str(self.amount_to_precision(symbol, amount)),
                'triggerPrice': str(self.price_to_precision(symbol, activation_price)), 
                'rangeRate': api_callback_rate_str, 
                **params
            }

            logger.info(f"Sende impliziten TSL-Aufruf: private_mix_post_plan_place_plan mit Params: {api_params}")
            response = self.exchange.private_mix_post_plan_place_plan(api_params)
            logger.info(f"TSL-Antwort von Bitget API: {response}")
            return response
        except AttributeError as e:
            logger.error(f"Implizite Methode für Trailing Stop nicht gefunden: {e}")
            raise ccxt.NotSupported("Trailing Stop via impliziter Methode nicht verfügbar.")
        except Exception as e:
            logger.error(f"Kritischer Fehler beim Aufruf der impliziten TSL-Methode: {e}", exc_info=True)
            raise e


# ---------------------------------------------------------------------------
# Papierhandel
# ---------------------------------------------------------------------------
class PapierExchange(Exchange):
    """Papierhandel (settings.json "echtgeld": {"aktiv": false}) mit derselben Schnittstelle wie Exchange.

    Kerzen und Kurse kommen oeffentlich von Bitget (kein Schluessel). Es geht nie eine Order an Bitget.
    - Kasse, Positionen, geschlossene Trades: artifacts/papier/konto.json (utils/papier.py, gleiche Datei wie
      jaegerbot/zockerbot -> das Cockpit liest sie).
    - Wartende Limit-Orders mit angehaengtem SL/TP (wie Bitget presetStopLoss/-SurplusPrice):
      artifacts/papier/orders.json. Fill, wenn eine abgeschlossene 1m-Kerze ab der naechsten vollen Minute nach
      dem Legen den Limitpreis erreicht (zum Limit bzw. zur besseren Eroeffnung bei einer Luecke), Maker 0,02 %.
      SL/TP gelten ab der Fill-Kerze (Stopp vor Ziel in derselben Kerze, wie PapierKonto.abrechnen).
    - master_runner startet je Strategie einen eigenen Prozess; alle teilen ein Konto. Jeder Zugriff laeuft
      deshalb unter einer Dateisperre und liest den Stand vorher frisch von der Platte.
    """
    papier = True
    MAKER = 0.0002
    ALLE_ABRECHNEN_MS = 60_000          # Abrechnung aller Symbole hoechstens einmal pro Minute (Kontostand)
    AUFBEWAHREN_MS = 30 * 86_400_000    # erledigte Orders 30 Tage behalten

    def __init__(self, konto_pfad, start):
        super().__init__({})
        from fibot.utils.papier import PapierKonto
        self.ordner = os.path.dirname(os.path.abspath(konto_pfad))
        os.makedirs(self.ordner, exist_ok=True)
        self.orders_pfad = os.path.join(self.ordner, 'orders.json')
        self.sperr_pfad = os.path.join(self.ordner, '.sperre')
        self._tiefe = 0
        self._lev = {}
        self._orders = {'orders': []}
        with self._tx():
            self.konto = PapierKonto(konto_pfad, start, self.exchange)

    # --- Sperre + Speicher ---
    @staticmethod
    def _sperren(fh):
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except ImportError:                       # Windows (nur lokale Tests)
            import msvcrt
            fh.seek(0)
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    return
                except OSError:
                    time.sleep(0.05)

    @staticmethod
    def _entsperren(fh):
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

    @contextmanager
    def _tx(self):
        if self._tiefe:
            self._tiefe += 1
            try:
                yield
            finally:
                self._tiefe -= 1
            return
        fh = open(self.sperr_pfad, 'a+')
        self._sperren(fh)
        try:
            self._laden()
            self._tiefe = 1
            yield
        finally:
            self._tiefe = 0
            self._entsperren(fh)
            fh.close()

    def _laden(self):
        if getattr(self, 'konto', None) is not None and os.path.exists(self.konto.path):
            with open(self.konto.path, encoding='utf-8') as f:
                self.konto.s = json.load(f)
        try:
            with open(self.orders_pfad, encoding='utf-8') as f:
                self._orders = json.load(f)
        except (OSError, ValueError):
            self._orders = {'orders': []}

    def _save_orders(self):
        tmp = self.orders_pfad + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._orders, f, indent=1)
        os.replace(tmp, self.orders_pfad)

    def _alle(self):
        return self._orders.setdefault('orders', [])

    @staticmethod
    def _ccxt_order(o):
        return {'id': o['id'], 'clientOrderId': o.get('clientOid'), 'symbol': o['symbol'], 'side': o['side'],
                'type': 'limit', 'price': o['price'], 'amount': o['amount'], 'filled': o['filled'],
                'remaining': o['amount'] - o['filled'], 'average': o.get('average'), 'status': o['status'],
                'info': {'presetStopLossPrice': o.get('sl'), 'presetStopSurplusPrice': o.get('tp'),
                         'papier_grund': o.get('grund')}}

    def _offene_margin(self):
        return sum(o['amount'] * o['price'] / o['lev'] * (1 + self.MAKER * o['lev'])
                   for o in self._alle() if o['status'] == 'open')

    # --- Abrechnung: erst Limit-Fills, dann SL/TP/Liquidation ---
    def _abrechnen(self, symbol=None):
        now = self.konto.now()
        if symbol is None and now - int(self._orders.get('alle_abgerechnet_ms') or 0) < self.ALLE_ABRECHNEN_MS:
            return
        geaendert = False
        for o in self._alle():
            if o['status'] != 'open' or (symbol and o['symbol'] != symbol):
                continue
            try:
                kerzen, step = self.konto._kerzen(o['symbol'], o['checked_ms'], now)
            except Exception:
                continue                       # Netz-Hickser: naechster Lauf prueft dieselben Kerzen
            kauf = o['side'] == 'buy'
            for t, op, h, l, c, *_ in kerzen:
                if (l <= o['price']) if kauf else (h >= o['price']):
                    self._fill(o, min(op, o['price']) if kauf else max(op, o['price']), t)
                    break
                o['checked_ms'] = int(t + step)
            geaendert = True
        for p in list(self.konto.positionen):
            if symbol is None or p['symbol'] == symbol:
                self._position_abrechnen(p, now)
        if symbol is None:
            self._orders['alle_abgerechnet_ms'] = now
            geaendert = True
        if geaendert:
            self._save_orders()
        self.konto.save()

    def _position_abrechnen(self, p, now):
        """Dieselben Regeln wie PapierKonto.abrechnen(), aber fuer eine Position (ein Symbol je Prozess)."""
        try:
            kerzen, step = self.konto._kerzen(p['symbol'], p['checked_ms'], now)
        except Exception:
            return
        lng = p['side'] == 'long'
        for t, o, h, l, c, *_ in kerzen:
            stop = (max(p['sl'] or 0.0, p['liq']) if lng else min(p['sl'] or float('inf'), p['liq']))
            if (l <= stop) if lng else (h >= stop):
                if p['sl'] is None or (lng and p['liq'] >= p['sl']) or (not lng and p['liq'] <= p['sl']):
                    self.konto.schliessen(p, p['liq'], 'Liquidation', t + step, liquidiert=True, kerzen=kerzen)
                else:
                    self.konto.schliessen(p, min(o, p['sl']) if lng else max(o, p['sl']), 'SL', t + step,
                                          kerzen=kerzen)
                return
            if p['tp'] is not None and ((h >= p['tp']) if lng else (l <= p['tp'])):
                self.konto.schliessen(p, max(o, p['tp']) if lng else min(o, p['tp']), 'TP', t + step,
                                      mit_spread=False, kerzen=kerzen)
                return
            p['checked_ms'] = int(t + step)
        self.konto.funding_buchen(p, p['checked_ms'], kerzen)   # Funding bis zur zuletzt geprüften Kerze

    def _fill(self, o, px, t):
        side = 'long' if o['side'] == 'buy' else 'short'
        k = self.konto
        if k.position(o['symbol'], side):
            o.update(status='canceled', grund='Position schon offen')
            return
        lev = o['lev']
        margin, fee = o['amount'] * px / lev, o['amount'] * px * self.MAKER
        if margin + fee > k.s['cash'] + 1e-9:
            o.update(status='canceled', grund='zu wenig Guthaben beim Fill')
            return
        k.s['cash'] -= margin + fee
        k.positionen.append({'symbol': o['symbol'], 'side': side, 'qty': o['amount'], 'entry': px, 'lev': lev,
                             'margin': margin, 'fee_in': fee, 'sl': o.get('sl'), 'tp': o.get('tp'),
                             'liq': k.liq_preis(px, side, lev), 'opened_ms': int(t), 'checked_ms': int(t),
                             'order_id': o['id']})
        o.update(status='closed', filled=o['amount'], average=px, fill_ms=int(t))
        logger.info(f"PAPIER Fill: {o['side'].upper()} {o['amount']} {o['symbol']} @ {px:.6g} "
                    f"| SL {o.get('sl')} | TP {o.get('tp')}")

    # --- Konto ---
    def fetch_balance_usdt(self):
        with self._tx():
            self._abrechnen()
            return max(0.0, self.konto.s['cash'] - self._offene_margin())

    def fetch_equity_usdt(self):
        with self._tx():
            self._abrechnen()
            kurse = {}
            for p in self.konto.positionen:
                try:
                    kurse[p['symbol']] = self.konto.kurs(p['symbol'])
                except Exception:
                    pass
            return self.konto.kontostand(kurse)

    def set_margin_mode(self, symbol, margin_mode='isolated'):
        return True

    def set_leverage(self, symbol, leverage, margin_mode='isolated'):
        self._lev[symbol] = int(leverage)
        return True

    # --- Positionen ---
    def fetch_open_positions(self, symbol: str, strict: bool = False):
        with self._tx():
            self._abrechnen(symbol)
            out = []
            for p in self.konto.positionen:
                if symbol and p['symbol'] != symbol:
                    continue
                try:
                    upnl = self.konto.offen_pnl(p, self.konto.kurs(p['symbol']))
                except Exception:
                    upnl = 0.0
                out.append({'symbol': p['symbol'], 'side': p['side'], 'contracts': p['qty'],
                            'entryPrice': p['entry'], 'unrealizedPnl': upnl, 'initialMargin': p['margin'],
                            'leverage': p['lev'], 'liquidationPrice': p['liq'],
                            'stopLossPrice': p.get('sl'), 'takeProfitPrice': p.get('tp')})
            return out

    def close_position(self, symbol: str, side: Optional[str] = None):
        with self._tx():
            for p in list(self.konto.positionen):
                if p['symbol'] == symbol and (side is None or p['side'] == side):
                    return self.place_market_order(symbol, 'sell' if p['side'] == 'long' else 'buy',
                                                   p['qty'], reduce=True)
        return None

    # --- Orders ---
    def place_limit_order_with_tpsl(self, symbol: str, side: str, amount: float, price: float,
                                    sl_price: float, tp_price: float, client_oid: str = None):
        with self._tx():
            self._abrechnen(symbol)
            amt = float(self.amount_to_precision(symbol, amount))
            px = float(self.price_to_precision(symbol, price))
            sl = float(self.price_to_precision(symbol, sl_price))
            tp = float(self.price_to_precision(symbol, tp_price))
            if (side == 'buy' and not sl < px < tp) or (side == 'sell' and not tp < px < sl):
                raise ccxt.InvalidOrder(f'Papier: SL/TP liegen falsch zum Limit ({sl} / {px} / {tp})')
            if client_oid and any(o.get('clientOid') == client_oid for o in self._alle()):
                raise ccxt.InvalidOrder(f'Papier: clientOid {client_oid} schon vergeben')
            lev = self._lev.get(symbol, 1)
            if amt * px / lev * (1 + self.MAKER * lev) > self.konto.s['cash'] - self._offene_margin() + 1e-9:
                raise ccxt.InsufficientFunds('Papier: zu wenig freies Guthaben fuer die Limit-Order')
            now = self.konto.now()
            o = {'id': f'papier-{now}-{len(self._alle())}', 'clientOid': client_oid, 'symbol': symbol,
                 'side': side, 'amount': amt, 'price': px, 'sl': sl, 'tp': tp, 'lev': lev, 'status': 'open',
                 'filled': 0.0, 'average': None, 'created_ms': now,
                 'checked_ms': (now // 60_000 + 1) * 60_000}
            alt = now - self.AUFBEWAHREN_MS
            self._orders['orders'] = [x for x in self._alle() if x['status'] == 'open' or x['created_ms'] >= alt]
            self._alle().append(o)
            self._save_orders()
            logger.info(f"PAPIER Limit: {side.upper()} {amt} {symbol} @ {px} | SL {sl} | TP {tp}")
            return self._ccxt_order(o)

    def place_limit_order(self, symbol: str, side: str, amount: float, price: float, reduce: bool = False,
                          params={}):
        raise ccxt.NotSupported('Papier: nur Konfluenz-Orders mit SL/TP (place_limit_order_with_tpsl)')

    def _finde(self, id=None, client_oid=None):
        for o in self._alle():
            if (id and o['id'] == str(id)) or (client_oid and o.get('clientOid') == client_oid):
                return o
        return None

    def fetch_order(self, id: str, symbol: str):
        with self._tx():
            self._abrechnen(symbol)
            o = self._finde(id=id)
            return self._ccxt_order(o) if o else None

    def fetch_order_by_client_oid(self, client_oid: str, symbol: str):
        if not client_oid:
            raise ValueError('clientOid fehlt')
        with self._tx():
            self._abrechnen(symbol)
            o = self._finde(client_oid=client_oid)
            return self._ccxt_order(o) if o else None

    def fetch_open_orders(self, symbol: str, strict: bool = False):
        with self._tx():
            self._abrechnen(symbol)
            return [self._ccxt_order(o) for o in self._alle() if o['status'] == 'open' and o['symbol'] == symbol]

    def cancel_order(self, id: str, symbol: str):
        with self._tx():
            self._abrechnen(symbol)
            o = self._finde(id=id)
            if o is None:
                raise ccxt.OrderNotFound(f'Papier: Order {id} unbekannt')
            if o['status'] == 'open':
                o['status'] = 'canceled'
                self._save_orders()
            return self._ccxt_order(o)

    def cancel_all_orders_for_symbol(self, symbol, strict: bool = False):
        """Storniert wartende Limit-Orders. SL/TP einer offenen Papierposition bleiben (sie haengen an ihr)."""
        with self._tx():
            self._abrechnen(symbol)
            n = 0
            for o in self._alle():
                if o['status'] == 'open' and o['symbol'] == symbol:
                    o['status'] = 'canceled'
                    n += 1
            if n:
                self._save_orders()
            return n

    def cancel_stale_entry_orders(self, keep_symbols):
        with self._tx():
            out = []
            for o in self._alle():
                if o['status'] == 'open' and o['symbol'] not in keep_symbols:
                    o['status'] = 'canceled'
                    out.append((o['symbol'], o['id']))
            if out:
                self._save_orders()
            return out

    def fetch_open_trigger_orders(self, symbol: str, strict: bool = False):
        return []

    def fetch_closed_trigger_orders(self, symbol: str, limit: int = 20):
        return []

    def fetch_position_tpsl_orders(self, symbol: str, strict: bool = False):
        """SL/TP der Papierposition im Format der Bitget-Position-TP/SL (fuer den Schutzorder-Check)."""
        with self._tx():
            out = []
            for p in self.konto.positionen:
                if p['symbol'] != symbol:
                    continue
                for art in ('sl', 'tp'):
                    if p.get(art) is not None:
                        out.append({'id': f"papier-{art}-{p['opened_ms']}", 'triggerPrice': p[art],
                                    'info': {'triggerPrice': p[art],
                                             'planType': 'loss_plan' if art == 'sl' else 'profit_plan'}})
            return out

    def place_trigger_market_order(self, symbol: str, side: str, amount: float, trigger_price: float,
                                   reduce: bool = False, params={}):
        """Selbstreparatur: setzt SL bzw. TP der Papierposition (je nach Lage zum Einstieg)."""
        with self._tx():
            side_pos = 'long' if side == 'sell' else 'short'
            p = self.konto.position(symbol, side_pos)
            if p is None:
                raise ccxt.InvalidOrder('Papier: keine Position fuer die Trigger-Order')
            px = float(self.price_to_precision(symbol, trigger_price))
            ist_sl = px < p['entry'] if side_pos == 'long' else px > p['entry']
            self.konto.setze(symbol, side_pos, sl=px if ist_sl else None, tp=None if ist_sl else px)
            return {'id': f"papier-{'sl' if ist_sl else 'tp'}-{p['opened_ms']}", 'triggerPrice': px}

    def place_market_order(self, symbol: str, side: str, amount: float, reduce: bool = False, params={}):
        with self._tx():
            kurs = self.konto.kurs(symbol)
            if reduce:
                p = self.konto.position(symbol, 'long' if side == 'sell' else 'short')
                if p is None:
                    return None
                self.konto.schliessen(p, kurs, 'Market')
                logger.info(f"PAPIER Market-Schliessung: {symbol} {p['side']} @ {kurs:.6g}")
                return {'id': f'papier-close-{self.konto.now()}', 'average': kurs, 'filled': p['qty'],
                        'status': 'closed'}
            amt = float(self.amount_to_precision(symbol, amount))
            p = self.konto.eroeffnen(symbol, 'long' if side == 'buy' else 'short', amt, kurs,
                                     self._lev.get(symbol, 1))
            return {'id': f"papier-{p['opened_ms']}", 'average': p['entry'], 'filled': amt, 'status': 'closed'}
