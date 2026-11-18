// CUDA-Nachbau von confluence_logic._plan_one_direction + signal_exit.
// Ein Thread = eine Parameter-Kombination in einer Richtung (Long oder
// gespiegelte Short-Reihe). Rechnet sequenziell ueber alle Kerzen, exakt in
// derselben Reihenfolge und mit denselben double-Operationen wie Python.
#define RING 128

__device__ __forceinline__ double rmax(const double* sp, const int* lg, int n, int lo, int hi) {
  int lev = lg[hi - lo + 1];
  double a = sp[(size_t)lev * n + lo], b = sp[(size_t)lev * n + hi - (1 << lev) + 1];
  return a > b ? a : b;
}

__device__ __forceinline__ double rmin(const double* sp, const int* lg, int n, int lo, int hi) {
  int lev = lg[hi - lo + 1];
  double a = sp[(size_t)lev * n + lo], b = sp[(size_t)lev * n + hi - (1 << lev) + 1];
  return a < b ? a : b;
}

extern "C" __global__ void plan(
    const double* H, const double* L, const double* C, const double* atr,
    const int* prevL, const int* prevH,
    const unsigned char* valid, const long long* apos, const double* slope,
    const double* icpt, const double* width,
    const double* spH, const double* spC, const int* lg,
    const int* cch, const int* ckidx, const int* ck, const int* cwin,
    const double* cpar, double touch_atr, double cost_pct, int tp_upper,
    int ncombo, int base, int n, int write,
    int* counts, const long long* offsets,
    int* ev_i, int* ev_x, float* ev_r) {
  int ci = base + blockDim.x * blockIdx.x + threadIdx.x;
  if (ci >= ncombo) return;
  int ch = cch[ci], ki = ckidx[ci], k = ck[ci], win = cwin[ci];
  const double* P = cpar + 8 * (size_t)ci;
  double fib_lo = P[0], fib_hi = P[1], fib_sl = P[2], ztol = P[3];
  double slb = P[4], rr = P[5], age = P[6], bnear = P[7];
  const unsigned char* V = valid + (size_t)ch * n;
  const long long* AP = apos + (size_t)ch * n;
  const double* S = slope + (size_t)ch * n;
  const double* I = icpt + (size_t)ch * n;
  const double* W = width + (size_t)ch * n;
  const int* PL = prevL + (size_t)ki * n;
  const int* PH = prevH + (size_t)ki * n;
  int used[RING];
  int nu = 0, head = 0, cnt = 0;
  long long off = write ? offsets[ci] : 0;
  for (int i = win + k + 1; i < n; i++) {
    int j = i - 1;
    if (!V[j]) continue;
    double a = atr[j];
    double sl_ = S[j], ic = I[j], w = W[j];
    long long a0 = AP[j];
    int A = -1;
    int x = PL[j - k];
    while (x >= 0 && x >= a0) {
      if (fabs(L[x] - (ic + sl_ * x)) <= touch_atr * a) { A = x; break; }
      x = x > 0 ? PL[x - 1] : -1;
    }
    if (A < 0) continue;
    int B = -1; double hb = -1.0e300;
    x = PH[j - k];
    while (x > A) {
      if (H[x] >= hb) { hb = H[x]; B = x; }   // frueheste Position bei Gleichstand (np.argmax)
      x = x > 0 ? PH[x - 1] : -1;
    }
    if (B < 0) continue;
    bool isused = false;
    for (int u = 0; u < nu; u++) if (used[u] == B) { isused = true; break; }
    if (isused) continue;
    if (H[B] < ic + sl_ * B + w - bnear * a) continue;
    double hi = H[B], lo = L[A];
    if (rmax(spH, lg, n, B, j) > hi) continue;
    double diff = hi - lo;
    double f50 = hi - fib_lo * diff;
    double f618 = hi - fib_hi * diff;
    double f786 = hi - fib_sl * diff;
    if (rmin(spC, lg, n, B, j) < f786) {
      used[head] = B; head = (head + 1) % RING; if (nu < RING) nu++;
      continue;
    }
    if (age > 0 && (double)(i - B) > age * (double)(B - A)) continue;
    double limit = ic + sl_ * i;
    double tol = ztol * a;
    if (!(f618 - tol <= limit && limit <= f50 + tol) || C[j] <= limit) continue;
    double raw = (limit < f786 ? limit : f786) - slb * a;
    double md = fabs(limit) * 0.003;
    double ma = a * 0.30;
    if (ma > md) md = ma;
    double dist = limit - raw;
    if (md > dist) dist = md;
    double sl = limit - dist;
    double tp = tp_upper ? ic + sl_ * i + w : hi;
    if (limit - sl <= 0 || (tp - limit) / (limit - sl) < rr) continue;
    if (L[i] <= limit) {
      bool inst = L[i] <= sl;
      used[head] = B; head = (head + 1) % RING; if (nu < RING) nu++;
      if (write) {
        int ex = -1; double exitp = 0.0;
        if (inst) { ex = i; exitp = sl; }
        else {
          for (int t = i + 1; t < n; t++) {
            bool sh = L[t] <= sl, th = H[t] >= tp;
            if (sh || th) { ex = t; exitp = sh ? sl : tp; break; }
          }
        }
        float r = nanf("");
        if (ex >= 0) {
          double risk = limit - sl;
          double gross = (exitp - limit) / risk;
          double cost = fabs(limit) * cost_pct / risk;
          r = (float)(gross - cost);
        }
        ev_i[off + cnt] = i; ev_x[off + cnt] = ex; ev_r[off + cnt] = r;
      }
      cnt++;
    }
  }
  if (!write) counts[ci] = cnt;
}

// Long/Short zusammenfuehren (gleiche Kerze: Long behalten), Trendfilter,
// eine Position zur Zeit (busy), Monatssummen je Kombination.
extern "C" __global__ void combine(
    const long long* offL, const int* cntL, const int* eiL, const int* exL, const float* rL,
    const long long* offS, const int* cntS, const int* eiS, const int* exS, const float* rS,
    const unsigned char* okL, const unsigned char* okS, const short* monthL, const short* monthS,
    int nmonth, int ncombo, float* msum, int* mcnt, int* mwin, int by_exit, int with_counts) {
  int ci = blockDim.x * blockIdx.x + threadIdx.x;
  if (ci >= ncombo) return;
  int a = 0, b = 0, na = cntL[ci], nb = cntS[ci];
  long long oa = offL[ci], ob = offS[ci];
  int busy = -1;
  const int BIG = 2147483647;
  while (a < na || b < nb) {
    int ia = a < na ? eiL[oa + a] : BIG;
    int ib = b < nb ? eiS[ob + b] : BIG;
    int idx, ex; float r; bool ok;
    const short* month;
    if (ia <= ib) {
      idx = ia; ex = exL[oa + a]; r = rL[oa + a]; ok = okL[idx]; a++; month = monthL;
      if (ib == ia) b++;
    } else {
      idx = ib; ex = exS[ob + b]; r = rS[ob + b]; ok = okS[idx]; b++; month = monthS;
    }
    if (!ok) continue;
    if (idx <= busy) continue;
    if (ex < 0) continue;
    busy = ex;
    int m = by_exit ? month[ex] : month[idx];
    if (m < 0) continue;
    size_t q = (size_t)ci * nmonth + m;
    msum[q] += r;
    if (with_counts) { mcnt[q] += 1; if (r > 0) mwin[q] += 1; }
  }
}
