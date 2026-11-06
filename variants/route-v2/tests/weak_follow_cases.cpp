#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
struct F {
 std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine e{c.get()};
 int16_t m[NVT_NODES],decoded[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];unsigned counter=0;
 F(){nvt_touch_reset(c.get());flat();build(2);assert(e.frame(raw,sizeof raw,0,decoded,out,NVT_SLOTS)==-1);}
 void flat(){for(auto &v:m)v=5000;}
 void peak(int col,int amount){flat();m[20*NVT_COLUMNS+col]=(int16_t)(5000+amount);}
 void build(unsigned type=4,unsigned data=0){std::memset(raw,0,sizeof raw);++counter;raw[259]=(uint8_t)counter;raw[260]=(uint8_t)(counter>>8);raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)data;std::memcpy(raw+321,m,sizeof m);}
 int step(uint64_t t,unsigned data=0){(void)e.expire(t,out,NVT_SLOTS);build(4,data);return e.frame(raw,sizeof raw,t,decoded,out,NVT_SLOTS);}
 int confirm(){peak(20,1000);assert(step(1000)==0);assert(step(9333)==1);return out[0].tracking_id;}
 const nvt_slot &slot(int id)const{for(const auto &s:c->slots)if(s.active&&s.tracking_id==id)return s;assert(false);return c->slots[0];}
};
int main(int argc,char **argv){
 assert(argc==2);bool fixed=std::strcmp(argv[1],"experiment")==0;
 int weakmotion=0,recoverystep=0,rawmotion=0,lifttail=0;uint64_t stronghash=1469598103934665603ULL;unsigned tests=0;
 {F f;int id=f.confirm();int origin=f.out[0].x;int raworigin=f.slot(id).x,last=origin;uint64_t t=9333;
  for(unsigned i=1;i<=70;++i){t+=8333;f.peak(20+(i<10?i:10),280);assert(f.step(t)==1&&f.out[0].tracking_id==id);assert(f.out[0].x>=last&&f.out[0].x<=f.slot(id).x);last=f.out[0].x;}
  weakmotion=f.out[0].x-origin;rawmotion=f.slot(id).x-raworigin;
  assert(f.c->observation_cancelled==0&&f.c->dropout_expired==0);
  if(fixed)assert(weakmotion>rawmotion*9/10);else assert(weakmotion==0);
  int before=f.out[0].x;f.peak(30,1000);assert(f.step(t+8333)==1&&f.out[0].tracking_id==id);recoverystep=f.out[0].x-before;++tests;}
 {F f;int id=f.confirm(),origin=f.out[0].x;f.peak(21,220);assert(f.step(17666)==1&&f.out[0].tracking_id==id&&f.out[0].x==origin);++tests;}
 {F f;int id=f.confirm();f.peak(20,219);assert(f.step(17666)==1&&f.out[0].tracking_id==id&&f.slot(id).missed==1);assert(f.e.expire(34333,f.out,NVT_SLOTS)==0&&f.c->dropout_expired==1);++tests;}
 {F f;f.peak(20,280);for(int i=1;i<=8;++i)assert(f.step((uint64_t)i*8333)==0);++tests;}
 {F f;int id=f.confirm();f.peak(20,6500);assert(f.step(17666,0x1d)==TouchEngine::SpecialP);assert(f.slot(id).last_observed_us==9333);assert(f.e.expire(109333,f.out,NVT_SLOTS)==0&&f.c->observation_cancelled==1);++tests;}
 {F f;f.confirm();f.flat();assert(f.step(17666)==0);++tests;}
 {F f;f.confirm();int origin=f.out[0].x;const int amplitudes[]={295,280,260,240,221};uint64_t t=9333;
  for(int a:amplitudes){t+=8333;f.flat();f.m[20*NVT_COLUMNS+20]=5000+a;f.m[20*NVT_COLUMNS+21]=5000+a*40/100;assert(f.step(t)==1);}
  lifttail=f.out[0].x-origin;if(fixed)assert(lifttail>=0);else assert(lifttail==0);f.flat();assert(f.step(t+8333)==0);++tests;}
 {F f;f.confirm();uint64_t t=9333;for(int i=0;i<400;++i){t+=8333;f.flat();int phase=(i/18)%14;int c=20+(phase<=7?phase:14-phase),a=1000+i%200;f.m[20*NVT_COLUMNS+c]=5000+a;f.m[20*NVT_COLUMNS+c+1]=5000+a/3;int n=f.step(t);assert(n==1);stronghash=(stronghash^(uint64_t)f.out[0].tracking_id)*1099511628211ULL;stronghash=(stronghash^(uint64_t)f.out[0].x)*1099511628211ULL;stronghash=(stronghash^(uint64_t)f.out[0].y)*1099511628211ULL;}++tests;}
 {F f;f.confirm();f.c->timed_enabled=0;f.peak(21,280);int old=f.out[0].x;assert(nvt_touch_process(f.c.get(),f.m,4,f.out,NVT_SLOTS)==1&&f.out[0].x==old);++tests;}
 {F f;f.peak(20,1000);assert(f.step(1000)==0);int origin=f.c->slots[0].x;long fx=f.c->slots[0].fx;f.peak(21,280);assert(f.step(9333)==1&&f.out[0].x==origin&&f.c->slots[0].fx==fx);++tests;}
 std::printf("{\"mode\":\"%s\",\"tests\":%u,\"weak_raw_motion\":%d,\"weak_report_motion\":%d,\"recovery_report_step\":%d,\"lift_tail_report_delta\":%d,\"strong_400_report_hash\":\"%llx\"}\n",argv[1],tests,rawmotion,weakmotion,recoverystep,lifttail,(unsigned long long)stronghash);
}
