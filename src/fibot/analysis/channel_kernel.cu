extern "C" __global__ void channels(
 const double* h, const double* l, const double* c, const double* atr,
 const int* pl, const int* ph, int n, int k, int window, int maxp,
 int span, double breakatr, double breakfrac, double touchatr, double minwidth,
 int minupper, double* out) {
 int j=blockDim.x*blockIdx.x+threadIdx.x;
 if(j>=n || j<window+k) return;
 double a=atr[j]; if(!isfinite(a) || a<=0) return;
 int lp[64], nl=0; int first=j-window;
 for(int t=first;t<=j-k;t++) if(pl[t]) {
   if(nl<maxp) lp[nl++]=t;
   else {for(int z=1;z<maxp;z++)lp[z-1]=lp[z];lp[maxp-1]=t;}
 }
 if(nl<2) return;
 int besttouch=-1,bestp2=-1;
 for(int x=0;x<nl-1;x++) for(int y=x+1;y<nl;y++) {
   int p1=lp[x],p2=lp[y];
   if(p2-p1<2*k || l[p2]<=l[p1] || j-p1<span)continue;
   double slope=(l[p2]-l[p1])/(p2-p1),icpt=l[p1]-slope*p1;
   double allowed=breakfrac<=0?0:fmax(1.,breakfrac*(j-p1+1));
   int breaks=0;
   for(int t=p1;t<=j;t++) if(c[t]<icpt+slope*t-breakatr*a)breaks++;
   if(breaks>allowed)continue;
   bool bad=false; int touches=0;
   for(int z=x;z<nl;z++) {
     double dev=l[lp[z]]-(icpt+slope*lp[z]);
     if(dev< -breakatr*a)bad=true;
     if(fabs(dev)<=touchatr*a)touches++;
   }
   if(bad || touches<2)continue;
   double width=-1.e300; int nh=0;
   for(int t=p1;t<=j-k;t++) if(ph[t]) {
     width=fmax(width,h[t]-(icpt+slope*t));nh++;
   }
   if(nh==0 || width<minwidth*a)continue;
   breaks=0;
   for(int t=p1;t<=j;t++) if(c[t]>icpt+slope*t+width+breakatr*a)breaks++;
   if(breaks>allowed)continue;
   int upper=0;
   for(int t=p1;t<=j-k;t++)if(ph[t] && fabs(h[t]-(icpt+slope*t+width))<=touchatr*a)upper++;
   if(upper<minupper)continue;
   if(touches>besttouch || (touches==besttouch && p2>bestp2)) {
     besttouch=touches;bestp2=p2;
     out[j*5]=1;out[j*5+1]=p1;out[j*5+2]=slope;out[j*5+3]=icpt;out[j*5+4]=width;
   }
 }
}
