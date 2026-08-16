"""
Tushare data source adapter
"""
import logging
from datetime import datetime, timedelta
from app.utils.timezone import now_tz

import pandas as pd

from .base import DataSourceAdapter

logger = logging.getLogger(__name__)


class TushareAdapter(DataSourceAdapter):
    """Tusharedata source adapter"""

    def __init__(self):
        super().__init__()  # 调用父类初始化
        self._provider = None
        # trade_cal 接口每天有频控(20000次/天)，避免频繁调用 is_available 时被封
        self._cached_available: bool | None = None
        self._available_cache_ts: float = 0.0
        self._initialize()

    def _initialize(self):
        """Initialize Tushare provider"""
        try:
            from tradingagents.dataflows.providers.china.tushare import get_tushare_provider
            self._provider = get_tushare_provider()
        except Exception as e:
            logger.warning(f"Failed to initialize Tushare provider: {e}")
            self._provider = None

    @property
    def name(self) -> str:
        return "tushare"

    def _get_default_priority(self) -> int:
        return 3  # highest priority (数字越大优先级越高)  # highest priority

    def get_token_source(self) -> str | None:
        """获取 Token 来源"""
        if self._provider:
            return getattr(self._provider, "token_source", None)
        return None

    def is_available(self) -> bool:
        """Check whether Tushare is available"""
        import time as _time
        if self._provider is None:
            return False

        # 成功时缓存10分钟，失败时不缓存（立即重试），避免瞬态故障后无法快速恢复
        CACHE_TTL = 600.0
        now = _time.time()
        # 只在缓存值为 True 时使用缓存（成功时缓存），失败时不缓存
        if self._cached_available is True and (now - self._available_cache_ts) < CACHE_TTL:
            return True

        # 尝试直接使用 tushare API 测试连接
        result = False
        try:
            import tushare as ts
            # 获取 token（从环境变量或 provider）
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                logger.debug("Tushare: No token available")
                result = False
            else:
                ts.set_token(token)
                pro = ts.pro_api()
                # 优先使用 stock_basic（标准接口，验证 token 有效性），失败再用 daily 轻量查询
                try:
                    df = pro.stock_basic(ts_code='000001.SZ', fields='ts_code')
                    result = df is not None and len(df) > 0
                except Exception as _e1:
                    logger.debug(f"Tushare: stock_basic test failed, fallback to daily: {_e1}")
                    try:
                        # daily 接口：取最近 30 天数据（确保覆盖至少一个交易日）
                        from datetime import datetime, timedelta
                        end_date = now_tz().strftime('%Y%m%d')
                        start_date = (now_tz() - timedelta(days=30)).strftime('%Y%m%d')
                        df = pro.daily(ts_code='000001.SZ', start_date=start_date, end_date=end_date)
                        result = df is not None and len(df) > 0
                    except Exception as _e2:
                        logger.debug(f"Tushare: daily test failed: {_e2}")
                        result = False
        except Exception as e:
            logger.debug(f"Tushare: Connection test failed: {e}")
            result = False

        self._cached_available = result
        self._available_cache_ts = now
        return result

    def get_stock_list(self) -> pd.DataFrame | None:
        """Get stock list"""
        if not self.is_available():
            logger.warning("Tushare: Provider is not available")
            return None
        try:
            import tushare as ts
            # 获取 token
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                return None

            ts.set_token(token)
            pro = ts.pro_api()
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
            if df is not None and not df.empty:
                logger.info(f"Tushare: Successfully fetched {len(df)} stocks")
                return df
        except Exception as e:
            logger.error(f"Tushare: Failed to fetch stock list: {e}")
        return None

    def get_daily_basic(self, trade_date: str) -> pd.DataFrame | None:
        """Get daily basic financial data"""
        if not self.is_available():
            return None
        try:
            import tushare as ts
            # 获取 token
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                return None

            ts.set_token(token)
            pro = ts.pro_api()
            # 新增 ps, ps_ttm, total_share, float_share 字段
            fields = "ts_code,total_mv,circ_mv,pe,pb,ps,turnover_rate,volume_ratio,pe_ttm,pb_mrq,ps_ttm,total_share,float_share"
            df = pro.daily_basic(trade_date=trade_date, fields=fields)
            if df is not None and not df.empty:
                logger.info(
                    f"Tushare: Successfully fetched daily data for {trade_date}, {len(df)} records"
                )
                return df
        except Exception as e:
            logger.error(f"Tushare: Failed to fetch daily data for {trade_date}: {e}")
        return None


    def get_dividend_data(self, ts_code: str) -> pd.DataFrame | None:
        """获取个股分红送配数据（Tushare pro.dividend）。

        返回字段（单位说明）：
        - cash_div / cash_div_tax：每股现金分红，单位 元/股；
        - stk_div：每股送转股；
        - ann_date / ex_date / record_date / pay_date：公告日/除权除息日/股权登记日/派息日。
        """
        if not self.is_available():
            logger.warning("Tushare: Provider is not available")
            return None
        try:
            import tushare as ts
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")
            if not token:
                return None
            ts.set_token(token)
            pro = ts.pro_api()
            fields = ("ts_code,ann_date,end_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
                      "cash_div,cash_div_tax,record_date,ex_date,pay_date,base_date,base_share,float_share")
            df = pro.dividend(ts_code=ts_code, fields=fields)
            if df is not None and not df.empty:
                logger.info(f"Tushare: Successfully fetched dividend data for {ts_code}, {len(df)} records")
                return df
        except Exception as e:
            logger.error(f"Tushare: Failed to fetch dividend data for {ts_code}: {e}")
        return None

    def get_financial_data(self, ts_code: str, limit: int = 20) -> pd.DataFrame | None:
        """获取个股多期财务指标（Tushare pro.fina_indicator + income）。

        返回按报告期（end_date）倒序的多期财务数据，字段已映射为统一命名：
        - report_period 由 end_date 归一为 YYYYMMDD
        - grossprofit_margin -> gross_margin, or_yoy -> revenue_yoy
        - roe/roa/gross_margin/net_margin/revenue_yoy/net_profit_yoy/eps/bps 来自 fina_indicator
        - current_ratio/quick_ratio/debt_to_assets 来自 fina_indicator
        - revenue/net_profit（营收/净利绝对额）来自 pro.income，按报告期合并

        Args:
            ts_code: 带交易所后缀的代码，如 "600519.SH"
            limit: 最多返回的报告期数（默认 20 期，约 5 年）
        """
        if not self.is_available():
            return None
        try:
            import tushare as ts
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")
            if not token:
                return None
            ts.set_token(token)
            pro = ts.pro_api()
            fields = ("ts_code,ann_date,end_date,roe,roa,netprofit_margin,"
                      "grossprofit_margin,q_profit_yoy,netprofit_yoy,or_yoy,"
                      "debt_to_assets,current_ratio,quick_ratio,eps,bps,cfps,ocfps")
            df = pro.fina_indicator(ts_code=ts_code, fields=fields)
            if df is None or getattr(df, 'empty', True):
                return None
            # 按报告期倒序，取最近 limit 期
            df = df.sort_values('end_date', ascending=False).head(limit)
            # 字段映射为统一命名（保留原字段，另加别名，兼容筛选与个股详情两处消费方）
            df = df.rename(columns={
                'grossprofit_margin': 'gross_margin',
                'or_yoy': 'revenue_yoy',
            })
            if 'netprofit_margin' in df.columns:
                df['net_margin'] = df['netprofit_margin']
            if 'netprofit_yoy' in df.columns:
                df['net_profit_yoy'] = df['netprofit_yoy']

            # 补充营收/净利绝对额（pro.income），按报告期(end_date)合并
            try:
                inc_fields = "ts_code,end_date,revenue,total_revenue,n_income,n_income_attr_p"
                inc = pro.income(ts_code=ts_code, fields=inc_fields)
                if inc is not None and not getattr(inc, 'empty', True):
                    # 营收优先用 revenue（营业收入），缺失时回退 total_revenue（营业总收入）
                    if 'revenue' not in inc.columns and 'total_revenue' in inc.columns:
                        inc['revenue'] = inc['total_revenue']
                    elif 'revenue' in inc.columns and 'total_revenue' in inc.columns:
                        inc['revenue'] = inc['revenue'].fillna(inc['total_revenue'])
                    inc = inc.rename(columns={
                        'n_income': 'net_profit',
                        'n_income_attr_p': 'net_profit_attr',
                    })
                    sub = inc[['end_date', 'revenue', 'net_profit', 'net_profit_attr']].copy()
                    df = df.merge(sub, on='end_date', how='left')
            except Exception as inc_err:
                logger.warning(f"Tushare: income 补充失败（不影响 fina_indicator）: {inc_err}")

            logger.info(f"Tushare: Successfully fetched {len(df)} financial periods for {ts_code}")
            return df
        except Exception as e:
            logger.error(f"Tushare: Failed to fetch financial data for {ts_code}: {e}")
            return None

    def get_realtime_quotes(self):
        """Get full-market near real-time quotes via Tushare rt_k fallback
        Returns dict keyed by 6-digit code: {'000001': {'close': ..., 'pct_chg': ..., 'amount': ...}}
        """
        if not self.is_available():
            return None
        try:
            import tushare as ts
            # 获取 token
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                return None

            ts.set_token(token)
            pro = ts.pro_api()
            df = pro.rt_k(ts_code='3*.SZ,6*.SH,0*.SZ,9*.BJ')
            if df is None or getattr(df, 'empty', True):
                logger.warning('Tushare rt_k returned empty data')
                return None
            # Required columns
            if 'ts_code' not in df.columns or 'close' not in df.columns:
                logger.error(f'Tushare rt_k missing columns: {list(df.columns)}')
                return None
            result: dict[str, dict[str, float | None]] = {}
            for _, row in df.iterrows():
                ts_code = str(row.get('ts_code') or '')
                if not ts_code or '.' not in ts_code:
                    continue
                code6 = ts_code.split('.')[0].zfill(6)
                close = float(row.get('close')) if row.get('close') is not None else None
                pre_close = float(row.get('pre_close')) if row.get('pre_close') is not None else None
                amount_raw = float(row.get('amount')) if row.get('amount') is not None else None
                # amount 单位转换：Tushare rt_k 官方 amount 单位为 千元 → 统一为 元（×1000）
                amount = amount_raw * 1000.0 if amount_raw is not None else None
                # pct_chg may not be provided; compute if possible
                pct_chg = None
                if 'pct_chg' in df.columns and row.get('pct_chg') is not None:
                    try:
                        pct_chg = float(row.get('pct_chg'))
                    except Exception:
                        pct_chg = None
                if pct_chg is None and close is not None and pre_close is not None and pre_close not in (0, 0.0):
                    try:
                        pct_chg = (close / pre_close - 1.0) * 100.0
                    except Exception:
                        pct_chg = None
                # optional OHLC + volume
                op = None
                hi = None
                lo = None
                vol = None
                try:
                    if 'open' in df.columns:
                        op = float(row.get('open')) if row.get('open') is not None else None
                    if 'high' in df.columns:
                        hi = float(row.get('high')) if row.get('high') is not None else None
                    if 'low' in df.columns:
                        lo = float(row.get('low')) if row.get('low') is not None else None
                    # 成交量单位转换：Tushare 返回的是手，需要转换为股
                    if 'vol' in df.columns:
                        vol = float(row.get('vol')) if row.get('vol') is not None else None
                        if vol is not None:
                            vol = vol * 100  # 手 -> 股
                    elif 'volume' in df.columns:
                        vol = float(row.get('volume')) if row.get('volume') is not None else None
                        if vol is not None:
                            vol = vol * 100  # 手 -> 股
                except Exception:
                    pass
                result[code6] = {'close': close, 'pct_chg': pct_chg, 'amount': amount, 'volume': vol, 'open': op, 'high': hi, 'low': lo, 'pre_close': pre_close}
            return result
        except Exception as e:
            logger.error(f'Failed to fetch realtime quotes from Tushare rt_k: {e}')
            return None

    def get_kline(self, code: str, period: str = "day", limit: int = 120, adj: str | None = None):
        """Get K-line bars using tushare pro_bar
        period: day/week/month/5m/15m/30m/60m
        adj: None/qfq/hfq
        Returns: list of {time, open, high, low, close, volume, amount}
        """
        if not self.is_available():
            return None
        try:
            import tushare as ts
            from tushare.pro.data_pro import pro_bar
        except Exception:
            logger.error("Tushare pro_bar not available")
            return None
        try:
            # 获取 token
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                return None

            ts.set_token(token)
            pro = ts.pro_api()

            # normalize ts_code: 6-digit code -> ts_code format
            if '.' not in code:
                if code.startswith(('6', '9')):
                    ts_code = f"{code}.SH"
                elif code.startswith('8'):
                    ts_code = f"{code}.BJ"
                else:
                    ts_code = f"{code}.SZ"
            else:
                ts_code = code

            # map period -> freq
            freq_map = {
                "day": "D",
                "week": "W",
                "month": "M",
                "5m": "5min",
                "15m": "15min",
                "30m": "30min",
                "60m": "60min",
            }
            freq = freq_map.get(period, "D")
            adj_arg = adj if adj in (None, "qfq", "hfq") else None

            # 根据频率决定请求的字段
            if freq in ["5min", "15min", "30min", "60min"]:
                fields = "open,high,low,close,vol,amount,trade_date,trade_time"
            else:
                fields = "open,high,low,close,vol,amount,trade_date"

            df = pro_bar(ts_code=ts_code, api=pro, freq=freq, adj=adj_arg, limit=limit, fields=fields)
            if df is None or getattr(df, 'empty', True):
                return None
            # standardize columns
            items = []
            # choose time column
            tcol = 'trade_time' if 'trade_time' in df.columns else 'trade_date' if 'trade_date' in df.columns else None
            if tcol is None:
                logger.error(f'Tushare pro_bar missing time column: {list(df.columns)}')
                return None
            df = df.sort_values(tcol)
            for _, row in df.iterrows():
                tval = row.get(tcol)
                try:
                    time_str = str(tval)
                    items.append({
                        "time": time_str,
                        "open": float(row.get('open')) if row.get('open') is not None else None,
                        "high": float(row.get('high')) if row.get('high') is not None else None,
                        "low": float(row.get('low')) if row.get('low') is not None else None,
                        "close": float(row.get('close')) if row.get('close') is not None else None,
                        # 🔥 全局统一口径：volume=股（手×100），amount=元（Tushare pro_bar amount为千元，×1000）
                        "volume": (lambda v: v * 100 if v is not None else None)(float(row.get('vol')) if row.get('vol') is not None else None),
                        "amount": (lambda a: a * 1000.0 if a is not None else None)(float(row.get('amount')) if row.get('amount') is not None else None),
                    })
                except Exception:
                    continue
            return items
        except Exception as e:
            logger.error(f"Failed to fetch kline from Tushare: {e}")
            return None

    def get_news(self, code: str, days: int = 2, limit: int = 50, include_announcements: bool = True):
        """Try to fetch news/announcements via tushare pro api if available.
        Returns list of {title, source, time, url, type}
        """
        if not self.is_available():
            return None
        try:
            import tushare as ts
            # 获取 token
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                return None

            ts.set_token(token)
            pro = ts.pro_api()
        except Exception:
            return None

        items = []
        # resolve ts_code and date range
        try:
            # normalize ts_code: 6-digit code -> ts_code format
            if '.' not in code:
                if code.startswith(('6', '9')):
                    ts_code = f"{code}.SH"
                elif code.startswith('8'):
                    ts_code = f"{code}.BJ"
                else:
                    ts_code = f"{code}.SZ"
            else:
                ts_code = code
        except Exception:
            ts_code = code
        try:
            end = now_tz()
            start = end - timedelta(days=max(1, days))
            start_str = start.strftime('%Y%m%d')
            end_str = end.strftime('%Y%m%d')
        except Exception:
            start_str = end_str = ""
        # Attempt announcements first (if requested)
        try:
            if include_announcements:
                df_anns = pro.anns(ts_code=ts_code, start_date=start_str, end_date=end_str)
                if df_anns is not None and not df_anns.empty:
                    for _, row in df_anns.head(limit).iterrows():
                        items.append({
                            "title": row.get('title') or row.get('ann_title') or '',
                            "source": "tushare",
                            "time": str(row.get('ann_date') or row.get('pub_date') or ''),
                            "url": row.get('url') or row.get('ann_url') or '',
                            "type": "announcement",
                        })
        except Exception:
            pass
        # Attempt news
        try:
            df_news = pro.news(ts_code=ts_code, start_date=start_str, end_date=end_str)
            if df_news is not None and not df_news.empty:
                for _, row in df_news.head(max(0, limit - len(items))).iterrows():
                    items.append({
                        "title": row.get('title') or '',
                        "source": row.get('src') or 'tushare',
                        "time": str(row.get('pub_time') or row.get('pub_date') or ''),
                        "url": row.get('url') or '',
                        "type": "news",
                    })
        except Exception:
            pass
        return items if items else None

    def find_latest_trade_date(self) -> str | None:
        """Find latest trade date by probing Tushare"""
        if not self.is_available():
            return None
        try:
            import tushare as ts
            # 获取 token
            token = getattr(self._provider, 'token', None)
            if not token:
                import os
                token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")

            if not token:
                return None

            ts.set_token(token)
            pro = ts.pro_api()

            today = now_tz()
            for delta in range(0, 10):  # up to 10 days back
                d = (today - timedelta(days=delta)).strftime("%Y%m%d")
                try:
                    db = pro.daily_basic(trade_date=d, fields="ts_code,total_mv")
                    if db is not None and not db.empty:
                        logger.info(f"Tushare: Found latest trade date: {d}")
                        return d
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Tushare: Failed to find latest trade date: {e}")
        return None

