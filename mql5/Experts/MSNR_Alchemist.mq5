//+------------------------------------------------------------------+
//|                                              MSNR_Alchemist.mq5  |
//|         Alchemist MSNR — Malaysian SnR x SMC x CRT (mechanical)  |
//+------------------------------------------------------------------+
//| Standalone algorithmic port of the Alchemist MSNR strategy for    |
//| XAUUSD. No AI, no web — pure deterministic rules distilled from   |
//| the Alchemist MSNR course (EP1/EP2 + gold breakdown videos),      |
//| OrderBlock.net's fresh-level lifecycle and the printed playbook:  |
//|                                                                   |
//|  DIRECTION  D1 external structure (close pivots) confirmed by H1  |
//|             BOS in the same direction. Conflict = stand aside.    |
//|  LEVELS     H4 + D1: A/V levels (close of the first candle of an  |
//|             opposite-colour pair), GAP levels (same-colour pair,  |
//|             band >= gap_min x ATR), OCL levels (close of the      |
//|             first candle of a same-colour run).                   |
//|  FRESHNESS  fresh until a wick touches (H4 2-use / D1 4-use);     |
//|             a body close through breaks the level.                |
//|  TRIGGER    price reaches a fresh right-side level and the M30    |
//|             body does NOT close through it (the level reacted),   |
//|             then M30 body-closes through the last minor swing in  |
//|             the level's direction (the structure shift).          |
//|  ENTRY      market order at the trigger bar close.                |
//|  STOP       beyond the reaction extreme + SL buffer x ATR(M30).  |
//|  TARGET     nearest opposing level ahead that clears the stop     |
//|             distance; skip the trade if RR < min RR.              |
//|  TIME EXIT  flat after N M30 bars (~4 days for 200).              |
//|  SESSION    London/NY only (07:00-20:00 UTC), input-tunable.      |
//|                                                                   |
//| Runs on any chart; pipeline fires on each closed M30 bar. Level   |
//| book rebuilds on closed H4 bars; storyline on closed H1 bars.     |
//| Tested under Model=4 (real ticks) with ExecutionMode=100 ms.      |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

CTrade trade;

//+------------------------------------------------------------------+
//| Inputs                                                            |
//+------------------------------------------------------------------+
input group "=== Strategy core ==="
input int    InpBiasMode       = 0;      // storyline: 0 = D1 only, 1 = D1+H1 aligned
input double InpGapMinATR      = 0.10;   // GAP min band size (x ATR of its TF)
input int    InpOclRunMin      = 2;      // OCL min same-colour candles per run
input int    InpH4Bars         = 300;    // H4 history scanned for levels
input int    InpD1Bars         = 60;     // D1 history scanned for levels
input int    InpLevelMaxAgeBars= 300;    // level max age (bars of its own TF)
input double InpBreakBufATR    = 0.10;   // body-break buffer (x ATR of level TF)
input int    InpUsesH4         = 1;      // H4 level use budget (2-times rule)
input int    InpUsesD1         = 2;      // D1 level use budget (4-times rule)
input bool   InpRequireFresh   = false;  // entry only at never-touched levels (else 2x/4x budgets)
input int    InpStoryPivot     = 3;      // storyline close-pivot window (bars)
input int    InpSwingPivot     = 4;      // M30 minor swing pivot window

input group "=== Risk & execution ==="
input double InpSlBufATR       = 0.20;   // SL buffer beyond reaction extreme (x ATR M30)
input double InpMinRR          = 1.25;   // skip trades below this reward:risk
input int    InpTPMode         = 0;      // 0 = nearest opposing level, 1 = fixed RR
input double InpFixedRR        = 2.0;    // TP distance in R when TPMode=1
input int    InpEntryStyle     = 0;      // 0 = trigger (M30 swing break), 1 = sweep (enter at the sweep close)
input int    InpTimeExitBars   = 200;    // M30 bars before time exit (~4 days)
input bool   InpSessionFilter  = true;   // London/NY hours only
input int    InpSessionStart   = 7;      // session start hour (UTC)
input int    InpSessionEnd     = 20;     // session end hour (UTC)
input int    InpServerUTCOffs  = 0;      // broker server offset from UTC (hours)
input double InpMaxSpreadPts   = 300;    // skip entries when spread wider (points)
input int    InpMagic          = 999777; // order magic
input int    InpSlippagePts    = 50;     // max slippage (points)

input group "=== Sizing ==="
input bool   InpUseFixedLot    = true;   // true = fixed lot, false = risk %
input double InpFixedLot       = 0.01;   // fixed volume
input double InpRiskPercent    = 1.0;    // % of equity risked per trade
input double InpOneTrade       = true;   // one position at a time

input group "=== Sequencing (the Alchemist order: touch -> reaction -> shift) ==="
input int    InpTrigAfterTouch = 12;     // trigger close must be within N M30 bars of the level touch
input double InpSwingNearATR   = 0.50;   // broken minor swing must sit within X ATR of the level
input bool   InpRequireSweep   = false;  // require wick THROUGH the level then close-back (CRT trigger)
input int    InpReachBars      = 12;     // level-touch lookback window (M30 bars)

input group "=== Debug ==="
input bool   InpVerbose        = false;  // journal every pipeline evaluation

//+------------------------------------------------------------------+
//| Level book                                                        |
//+------------------------------------------------------------------+
#define LEVEL_KIND_A    0
#define LEVEL_KIND_V    1
#define LEVEL_KIND_GAP  2
#define LEVEL_KIND_OCL  3
#define SIDE_SUPPORT    1
#define SIDE_RESIST     -1

struct SLevel
  {
   double   price;
   int      side;       // SIDE_SUPPORT / SIDE_RESIST
   datetime born;
   int      tf;         // 0 = H4, 1 = D1
   int      kind;
   bool     fresh;      // never wick-touched since birth
   int      touches;    // wick touches since birth
   bool     broken;     // body closed through since birth
   bool     active;
  };

SLevel  g_book[];
int     g_book_n        = 0;
datetime g_book_built   = 0;        // H4 bar time the book was built on
datetime g_story_built  = 0;        // H1 bar time storyline computed on
int     g_bias          = 0;        // +1 BULL, -1 BEAR, 0 WAIT

datetime g_last_m30     = 0;        // last processed M30 bar time
datetime g_entry_time   = 0;        // position entry bar time
int     g_atr_m30       = INVALID_HANDLE;
int     g_atr_h4        = INVALID_HANDLE;
int     g_atr_d1        = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);

   g_atr_m30 = iATR(_Symbol, PERIOD_M30, 14);
   g_atr_h4  = iATR(_Symbol, PERIOD_H4, 14);
   g_atr_d1  = iATR(_Symbol, PERIOD_D1, 14);
   if(g_atr_m30 == INVALID_HANDLE || g_atr_h4 == INVALID_HANDLE || g_atr_d1 == INVALID_HANDLE)
     {
      Print("MSNR Alchemist: ATR handle init failed");
      return(INIT_FAILED);
     }

   if(MQLInfoInteger(MQL_TESTER))
      Print("MSNR Alchemist: tester run — expect Model=4 (real ticks) + ExecutionMode=100");
   Print("MSNR Alchemist initialised on ", _Symbol);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   if(g_atr_m30 != INVALID_HANDLE) IndicatorRelease(g_atr_m30);
   if(g_atr_h4  != INVALID_HANDLE) IndicatorRelease(g_atr_h4);
   if(g_atr_d1  != INVALID_HANDLE) IndicatorRelease(g_atr_d1);
  }

//+------------------------------------------------------------------+
//| Candle helpers (chronological arrays, index 0 = oldest)           |
//+------------------------------------------------------------------+
bool IsBull(const double o, const double c) { return(c > o); }
bool IsBear(const double o, const double c) { return(c < o); }

// Wilder ATR read from handle, index i (chronological)
double AtrAt(const int handle, const int pos, const int total)
  {
   double buf[];
   int want = MathMin(pos + 1, total);
   if(CopyBuffer(handle, 0, 0, want, buf) <= 0) return(0.0);
   return(buf[pos]);   // CopyBuffer keeps chronological order by default
  }

//+------------------------------------------------------------------+
//| Confirmed close-price pivots -> last break direction (bias)       |
//| Mirrors the Python storyline(): D1 external bias, H1 must agree.  |
//+------------------------------------------------------------------+
int PivotBias(double &close[], const int n, const int w, int &last_break_i)
  {
   last_break_i = -1;
   int dir = 0;
   int last_h = -1, last_l = -1;
   for(int j = w; j < n - w; j++)
     {
      double mx = close[j], mn = close[j];
      bool mh = true, ml = true;
      for(int k = j - w; k <= j + w; k++)
        {
         if(k == j) continue;
         if(close[k] > mx) { mx = close[k]; mh = (close[k] > close[j]); }
         if(close[k] < mn) { mn = close[k]; ml = (close[k] < close[j]); }
        }
      if(close[j] == mx && mh) last_h = j;
      else if(close[j] == mn && ml) last_l = j;
     }
   if(last_h < 0 || last_l < 0) return(0);
   // last close beyond the last pivot high
   int iu = -1, idn = -1;
   for(int x = last_h + 1; x < n; x++) if(close[x] > close[last_h]) { iu = x; break; }
   for(int x = last_l + 1; x < n; x++) if(close[x] < close[last_l]) { idn = x; break; }
   if(iu < 0 && idn < 0) return(0);
   if(idn < 0 || (iu >= 0 && iu >= idn)) { dir = 1;  last_break_i = iu; }
   else                                  { dir = -1; last_break_i = idn; }
   return(dir);
  }

int Storyline()
  {
   // D1 external structure + H1 alignment
   int need_d1 = MathMax(InpStoryPivot * 20 + 40, 120);
   MqlRates rd[];
   int nd = CopyRates(_Symbol, PERIOD_D1, 0, need_d1, rd);
   if(nd < 60) return(0);
   int ndc = nd - 1;                          // closed bars only
   double cd[]; ArrayResize(cd, ndc);
   for(int i = 0; i < ndc; i++) cd[i] = rd[i].close;

   MqlRates rh[];
   int nh = CopyRates(_Symbol, PERIOD_H1, 0, 400, rh);
   if(nh < 60) return(0);
   int nhc = nh - 1;
   double ch[]; ArrayResize(ch, nhc);
   for(int i = 0; i < nhc; i++) ch[i] = rh[i].close;

   int dummy;
   int d1_dir = PivotBias(cd, ndc, InpStoryPivot, dummy);
   if(d1_dir == 0) return(0);
   if(InpBiasMode == 0) return(d1_dir);          // D1-only storyline
   int h1_dir = PivotBias(ch, nhc, InpStoryPivot, dummy);
   if(d1_dir == h1_dir) return(d1_dir);
   return(0);
  }

//+------------------------------------------------------------------+
//| Level book: scan H4 + D1 closed bars for A/V/GAP/OCL levels,      |
//| then replay the freshness lifecycle on the level's native TF.     |
//+------------------------------------------------------------------+
void BookAdd(const double price, const int side, const datetime born,
             const int tf, const int kind)
  {
   int n = g_book_n;
   ArrayResize(g_book, n + 1, 64);
   g_book[n].price   = NormalizeDouble(price, _Digits);
   g_book[n].side    = side;
   g_book[n].born    = born;
   g_book[n].tf      = tf;
   g_book[n].kind    = kind;
   g_book[n].fresh   = true;
   g_book[n].touches = 0;
   g_book[n].broken  = false;
   g_book[n].active  = true;
   g_book_n = n + 1;
  }

void ScanLevels(const ENUM_TIMEFRAMES tf, const int max_bars, const int tf_id,
                const double gap_min_atr, const int ocl_run_min,
                const int handle_atr)
  {
   MqlRates r[];
   int n = CopyRates(_Symbol, tf, 0, max_bars + 2, r);
   if(n < 10) return;
   int nc = n - 1;                           // closed bars only (n-1 = forming)

   // ATR series once (chronological)
   double atr_buf[];
   ArrayResize(atr_buf, nc);
   for(int i = 0; i < nc; i++) atr_buf[i] = 0.0;
   int got = CopyBuffer(handle_atr, 0, 0, nc, atr_buf);
   if(got <= 0) return;

   for(int i = 1; i < nc - 1; i++)
     {
      // i = the first candle of the pair (chronological); i+1 the second.
      // Levels born at the close of candle i.
      datetime born = r[i].time;
      double a = atr_buf[i];
      if(a <= 0.0) continue;

      bool col_i = IsBull(r[i].open, r[i].close);
      bool col_j = IsBull(r[i+1].open, r[i+1].close);

      // --- A / V (opposite-colour pair, level = close of the first)
      if(col_i && !col_j)
         BookAdd(r[i].close, SIDE_RESIST, born, tf_id, LEVEL_KIND_A);
      else if(!col_i && col_j)
         BookAdd(r[i].close, SIDE_SUPPORT, born, tf_id, LEVEL_KIND_V);
      // --- GAP (same-colour pair with an untraded band)
      else if(col_i && col_j)
        {
         double gap = r[i+1].open - r[i].close;
         if(gap >= gap_min_atr * a)
            BookAdd(r[i].close, SIDE_SUPPORT, born, tf_id, LEVEL_KIND_GAP);
        }
      else if(!col_i && !col_j)
        {
         double gap = r[i].close - r[i+1].open;
         if(gap >= gap_min_atr * a)
            BookAdd(r[i].close, SIDE_RESIST, born, tf_id, LEVEL_KIND_GAP);
        }

      // --- OCL (one level per run: close of the FIRST candle of a
      //     same-colour run of >= ocl_run_min candles)
      int run = 1;
      int j = i + 1;
      while(j < nc && (IsBull(r[j].open, r[j].close) == col_i)) { run++; j++; }
      if(run >= ocl_run_min)
        {
         int ocl_side = col_i ? SIDE_SUPPORT : SIDE_RESIST;
         BookAdd(r[i].close, ocl_side, born, tf_id, LEVEL_KIND_OCL);
        }
     }
  }

// Lifecycle replay on the level's native timeframe:
//   wick touch  -> consumes freshness (fresh=false, touches++)
//   body close beyond price + buffer -> level broken (dead)
// born_idx is the CHRONOLOGICAL position of the birth bar; bars strictly
// AFTER birth (born_idx+1 .. n-1) drive the lifecycle.
void ReplayLife(SLevel &lv, const MqlRates &r[], const int n,
                const int born_idx, const double buf)
  {
   for(int j = born_idx + 1; j < n - 1; j++)   // closed bars after birth
     {
      bool touched = false;
      if(lv.side == SIDE_SUPPORT)
        {
         if(r[j].low <= lv.price) touched = true;
         if(r[j].close < lv.price - buf) { lv.broken = true; break; }
        }
      else
        {
         if(r[j].high >= lv.price) touched = true;
         if(r[j].close > lv.price + buf) { lv.broken = true; break; }
        }
      if(touched) { lv.fresh = false; lv.touches++; }
     }
  }

void RebuildBook()
  {
   g_book_n = 0;
   ArrayResize(g_book, 0, 1024);
   g_book_built = 0;

   // H4 book
   MqlRates rh[];
   int nh = CopyRates(_Symbol, PERIOD_H4, 0, InpH4Bars + 2, rh);
   if(nh < 10) return;
   ScanLevels(PERIOD_H4, InpH4Bars, 0, InpGapMinATR, InpOclRunMin, g_atr_h4);
   // age filter + lifecycle for H4 levels (chronological positions!)
   double buf_h4 = InpBreakBufATR * AtrAt(g_atr_h4, nh - 2, nh);
   for(int k = 0; k < g_book_n; k++)
     {
      if(g_book[k].tf != 0) continue;
      if(g_book[k].born < rh[0].time) { g_book[k].active = false; continue; }
      int born_series = iBarShift(_Symbol, PERIOD_H4, g_book[k].born, false);
      if(born_series < 0) { g_book[k].active = false; continue; }
      int born_chrono = nh - 1 - born_series;   // iBarShift counts from the newest
      if(born_chrono < 1 || born_chrono > nh - 3) { g_book[k].active = false; continue; }
      ReplayLife(g_book[k], rh, nh, born_chrono, buf_h4);
     }
   g_book_built = rh[nh - 2].time;   // last closed H4 bar

   // D1 book
   MqlRates rd[];
   int nd = CopyRates(_Symbol, PERIOD_D1, 0, InpD1Bars + 2, rd);
   if(nd < 10) return;
   int d1_before = g_book_n;
   ScanLevels(PERIOD_D1, InpD1Bars, 1, InpGapMinATR * 2.0, InpOclRunMin, g_atr_d1);
   double buf_d1 = InpBreakBufATR * AtrAt(g_atr_d1, nd - 2, nd);
   for(int k = d1_before; k < g_book_n; k++)
     {
      if(g_book[k].born < rd[0].time) { g_book[k].active = false; continue; }
      int born_series = iBarShift(_Symbol, PERIOD_D1, g_book[k].born, false);
      if(born_series < 0) { g_book[k].active = false; continue; }
      int born_chrono = nd - 1 - born_series;
      if(born_chrono < 1 || born_chrono > nd - 3) { g_book[k].active = false; continue; }
      ReplayLife(g_book[k], rd, nd, born_chrono, buf_d1);
     }

   if(InpVerbose)
      PrintFormat("MSNR book rebuilt: %d levels (%d D1), built on H4 bar %s",
                  g_book_n, g_book_n - d1_before, TimeToString(g_book_built));
  }

// Candidate list: right-side, alive, within the use budget
int Candidates(int &idx[], const int want_side, const bool require_fresh,
               const double px_now, const double max_dist)
  {
   ArrayResize(idx, 0, 64);
   for(int k = 0; k < g_book_n; k++)
     {
      SLevel lv = g_book[k];
      if(!lv.active || lv.broken) continue;
      if(lv.side != want_side) continue;
      int budget = (lv.tf == 0) ? InpUsesH4 : InpUsesD1;
      if(lv.touches >= budget) continue;
      if(require_fresh && !lv.fresh) continue;
      if(MathAbs(lv.price - px_now) > max_dist) continue;
      int n = ArraySize(idx);
      ArrayResize(idx, n + 1, 64);
      idx[n] = k;
     }
   return(ArraySize(idx));
  }

//+------------------------------------------------------------------+
//| M30 minor swing (confirmed close-pivot strictly before bar i)     |
//| Returns true if a later close (j+1..i) broke it in `dir`.         |
//+------------------------------------------------------------------+
bool SwingTrigger(const double &o[], const double &c[], const int n,
                  const int i, const int dir, const int w, double &swing_px)
  {
   swing_px = 0.0;
   int last_swing = -1;
   double swing_v = 0.0;
   for(int j = i - w; j >= w; j--)
     {
      double mx = c[j], mn = c[j];
      for(int k = j - w; k <= j + w; k++)
        {
         if(k == j) continue;
         if(k > i) break;                    // pivot window must be closed
         if(c[k] > mx) mx = c[k];
         if(c[k] < mn) mn = c[k];
        }
      bool is_h = (c[j] == mx), is_l = (c[j] == mn);
      if(dir > 0 && is_l) { last_swing = j; swing_v = c[j]; break; }
      if(dir < 0 && is_h) { last_swing = j; swing_v = c[j]; break; }
     }
   if(last_swing < 0) return(false);
   swing_px = swing_v;
   for(int x = last_swing + 1; x <= i; x++)
      if((dir > 0 && c[x] > swing_v) || (dir < 0 && c[x] < swing_v))
         return(true);
   return(false);
  }

//+------------------------------------------------------------------+
//| Position helpers                                                  |
//+------------------------------------------------------------------+
bool HasOpenPosition()
  {
   if(!PositionSelect(_Symbol)) return(false);
   return((long)PositionGetInteger(POSITION_MAGIC) == InpMagic);
  }

bool SessionOk(const datetime t)
  {
   if(!InpSessionFilter) return(true);
   MqlDateTime st;
   TimeToStruct(t, st);
   int utc_hour = st.hour - InpServerUTCOffs;
   if(utc_hour < 0) utc_hour += 24;
   if(utc_hour >= 24) utc_hour -= 24;
   return(utc_hour >= InpSessionStart && utc_hour < InpSessionEnd);
  }

double CalcLots(const double sl_distance)
  {
   double vol = InpFixedLot;
   if(!InpUseFixedLot)
     {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double risk_amt = equity * InpRiskPercent / 100.0;
      double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tick_val <= 0 || tick_sz <= 0 || sl_distance <= 0) return(InpFixedLot);
      double loss_per_lot = sl_distance / tick_sz * tick_val;
      if(loss_per_lot <= 0) return(InpFixedLot);
      vol = risk_amt / loss_per_lot;
     }
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step > 0) vol = MathFloor(vol / step) * step;
   vol = MathMax(vmin, MathMin(vmax, vol));
   return(NormalizeDouble(vol, 2));
  }

//+------------------------------------------------------------------+
//| The pipeline — runs on each closed M30 bar                        |
//+------------------------------------------------------------------+
void Pipeline()
  {
   // --- manage time exit on the open position
   if(HasOpenPosition() && g_entry_time > 0)
     {
      int held = (int)((TimeCurrent() - g_entry_time) / PeriodSeconds(PERIOD_M30));
      if(held >= InpTimeExitBars)
        {
         if(trade.PositionClose(_Symbol))
            PrintFormat("MSNR: time exit after %d M30 bars", held);
         g_entry_time = 0;
         return;
        }
      return;   // one trade at a time — nothing else while in position
     }

   // --- direction
   g_bias = Storyline();
   if(g_bias == 0) { if(InpVerbose) Print("MSNR: no aligned storyline — flat"); return; }

   // --- fresh right-side levels near price
   MqlRates m30[];
   int nm = CopyRates(_Symbol, PERIOD_M30, 0, 60, m30);
   if(nm < 10) return;
   int last = nm - 2;                        // last CLOSED M30 bar (nm-1 = forming)
   double px_now = m30[last].close;
   double atr30 = AtrAt(g_atr_m30, last, nm);
   if(atr30 <= 0) return;

   // chronological open/close arrays for the trigger scan
   double m30_open[], m30_close[];
   ArrayResize(m30_open, nm);
   ArrayResize(m30_close, nm);
   for(int i = 0; i < nm; i++) { m30_open[i] = m30[i].open; m30_close[i] = m30[i].close; }

   int want_side = (g_bias > 0) ? SIDE_SUPPORT : SIDE_RESIST;
   int dir = (g_bias > 0) ? 1 : -1;

   double max_dist = 3.0 * atr30;            // level must be nearby
   int idx[];
   int ncand = Candidates(idx, want_side, InpRequireFresh, px_now, max_dist);
   if(ncand == 0) { if(InpVerbose) Print("MSNR: no fresh right-side level near price"); return; }

   // nearest candidate
   int best = -1;
   double best_d = 1e30;
   for(int c = 0; c < ncand; c++)
     {
      double d = MathAbs(g_book[idx[c]].price - px_now);
      if(d < best_d) { best_d = d; best = idx[c]; }
     }
   SLevel lv = g_book[best];

   // --- the reaction: price reached the level in the last InpReachBars bars,
   //     and no M30 body closed through it
   bool reached = false, reacted = false;
   int touch_bar = -1;                        // first bar (chronological) that touched
   for(int i = MathMax(1, last - InpReachBars + 1); i <= last; i++)
     {
      double a_i = AtrAt(g_atr_m30, i, nm);
      if(lv.side == SIDE_SUPPORT)
        {
         if(m30[i].low <= lv.price + 0.05 * a_i) { reached = true; if(touch_bar < 0) touch_bar = i; }
         if(m30[i].close < lv.price - 0.10 * a_i) { reacted = true; break; }
        }
      else
        {
         if(m30[i].high >= lv.price - 0.05 * a_i) { reached = true; if(touch_bar < 0) touch_bar = i; }
         if(m30[i].close > lv.price + 0.10 * a_i) { reacted = true; break; }
        }
     }
   if(!reached || reacted)
     { if(InpVerbose) Print("MSNR: level reached=", reached, " reacted=", reacted, " — skip"); return; }

   // optional CRT-style sweep requirement: a wick THROUGH the level then a
   // close back inside, within the reaction window
   int sweep_bar = -1;
   if(InpRequireSweep)
     {
      for(int i = MathMax(1, last - InpReachBars + 1); i <= last; i++)
        {
         double a_i = AtrAt(g_atr_m30, i, nm);
         bool bar_swept;
         if(lv.side == SIDE_SUPPORT)
            bar_swept = (m30[i].low < lv.price - 0.05 * a_i && m30[i].close > lv.price);
         else
            bar_swept = (m30[i].high > lv.price + 0.05 * a_i && m30[i].close < lv.price);
         if(bar_swept && sweep_bar < 0) sweep_bar = i;
        }
      if(sweep_bar < 0) return;
     }

   // --- session filter (Alchemist: London/NY only)
   if(!SessionOk(m30[last].time)) return;

   double entry = 0.0;
   double ext = 0.0;
   if(InpEntryStyle == 1)
     {
      // sweep-sniper entry (scout parity): the sweep must be the JUST-CLOSED
      // bar; enter at its close, stop beyond the sweep extreme.
      if(sweep_bar != last) return;
      entry = m30[last].close;
      ext = (dir > 0) ? m30[last].low : m30[last].high;
     }
   else
     {
      // --- M30 structure-shift trigger (after the touch, near the level)
      double swing;
      if(!SwingTrigger(m30_open, m30_close, nm, last, dir, InpSwingPivot, swing)) return;
      if(touch_bar >= 0 && (last - touch_bar) > InpTrigAfterTouch) return;   // shift must follow the touch
      if(MathAbs(swing - lv.price) > InpSwingNearATR * atr30) return;        // the shift must live at the level
      entry = m30[last].close;
      // reaction extreme: since the level's birth is far back, use the last
      // 12 M30 bars (the approach into the level) for the extreme
      int seg_from = MathMax(1, last - 11);
      ext = (dir > 0) ? m30[seg_from].low : m30[seg_from].high;
      for(int i = seg_from + 1; i <= last; i++)
         ext = (dir > 0) ? MathMin(ext, m30[i].low) : MathMax(ext, m30[i].high);
     }
   double sl = (dir > 0) ? ext - InpSlBufATR * atr30 : ext + InpSlBufATR * atr30;
   double risk = MathAbs(entry - sl);
   if(risk <= 0) return;

   double tp;
   if(InpTPMode == 1)
      tp = entry + dir * InpFixedRR * risk;
   else
     {
      // nearest opposing level ahead that clears the stop distance
      int opp_side = (dir > 0) ? SIDE_RESIST : SIDE_SUPPORT;
      double best_tp = 0.0;
      double best_tpd = 1e30;
      for(int k = 0; k < g_book_n; k++)
        {
         SLevel o = g_book[k];
         if(!o.active || o.broken || o.side != opp_side) continue;
         double ahead = (dir > 0) ? (o.price - entry) : (entry - o.price);
         if(ahead <= risk) continue;                    // must clear the stop
         if(ahead < best_tpd) { best_tpd = ahead; best_tp = o.price; }
        }
      if(best_tpd >= 1e30) return;
      tp = best_tp;
     }

   double rr = MathAbs(tp - entry) / risk;
   if(rr < InpMinRR)
     { if(InpVerbose) PrintFormat("MSNR: RR %.2f < %.2f — skip", rr, InpMinRR); return; }

   // --- broker constraints: spread + min stop distance
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPts) { Print("MSNR: spread ", spread, " too wide — skip"); return; }
   long stops_lvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist = stops_lvl * _Point;
   if(MathAbs(entry - sl) < min_dist || MathAbs(tp - entry) < min_dist) return;

   // --- sizing + order
   double vol = CalcLots(risk);
   double point_val = _Point;
   double sl_norm = NormalizeDouble(sl, _Digits);
   double tp_norm = NormalizeDouble(tp, _Digits);

   bool ok;
   if(dir > 0) ok = trade.Buy(vol, _Symbol, 0.0, sl_norm, tp_norm, "MSNR_Alc");
   else        ok = trade.Sell(vol, _Symbol, 0.0, sl_norm, tp_norm, "MSNR_Alc");

   if(ok)
     {
      g_entry_time = m30[last].time;
      PrintFormat("MSNR ENTRY %s @ %.3f SL %.3f TP %.3f RR %.2f | %s/%s lvl %.3f bias %s",
                  dir > 0 ? "BUY" : "SELL", entry, sl_norm, tp_norm, rr,
                  lv.tf == 0 ? "H4" : "D1",
                  lv.kind == LEVEL_KIND_A ? "A" : lv.kind == LEVEL_KIND_V ? "V" :
                  lv.kind == LEVEL_KIND_GAP ? "GAP" : "OCL",
                  lv.price, g_bias > 0 ? "BULL" : "BEAR");
     }
   else
      Print("MSNR: order failed — ", trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Custom optimization criterion: win rate x profit factor,          |
//| floored by a minimum trade count so genetic search cannot win     |
//| with 2 lucky trades. Target: >= 70% win rate at positive PF.      |
//+------------------------------------------------------------------+
double OnTester()
  {
   const double trades = TesterStatistics(STAT_TRADES);
   const double wins   = TesterStatistics(STAT_PROFIT_TRADES);
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   if(trades < 10.0) return(0.0);
   if(pf <= 0.0 || pf > 100.0) pf = 100.0;          // cap runaway PF
   const double wr = wins / trades;
   return(wr * pf * MathSqrt(trades));
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // pipeline once per closed M30 bar
   datetime m30_time = iTime(_Symbol, PERIOD_M30, 0);
   if(m30_time == g_last_m30) return;
   g_last_m30 = m30_time;

   // rebuild the book on each new closed H4 bar
   datetime h4_time = iTime(_Symbol, PERIOD_H4, 0);
   if(h4_time != g_book_built) RebuildBook();

   if(g_book_n == 0) return;

   Pipeline();
  }
//+------------------------------------------------------------------+

