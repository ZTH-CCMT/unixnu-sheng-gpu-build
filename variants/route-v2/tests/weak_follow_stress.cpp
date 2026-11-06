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
int main(int argc,char **argv){assert(argc==2);bool fixed=std::strcmp(argv[1],"experiment")==0;int short_report=0,short_raw=0,max_lag=0,single_report=0,tail=0,jitter=0,multi_motion=0;unsigned tests=0;
 {F f;int id=f.confirm(),origin=f.out[0].x;uint64_t t=9333;for(int i=1;i<=10;++i){f.peak(20+i,280);t+=8333;assert(f.step(t)==1&&f.out[0].tracking_id==id);int lag=f.slot(id).x-f.out[0].x;assert(lag>=0);if(lag>max_lag)max_lag=lag;}short_report=f.out[0].x-origin;short_raw=f.slot(id).x-origin;f.flat();assert(f.step(t+8333)==0);if(fixed)assert(short_report>0);else assert(short_report==0);++tests;}
 {F f;f.confirm();int origin=f.out[0].x;f.peak(21,280);assert(f.step(17666)==1);single_report=f.out[0].x-origin;f.flat();assert(f.step(25999)==0);assert(single_report==0);++tests;}
 {F f;f.confirm();uint64_t t=9333;for(int i=1;i<=6;++i){f.peak(20+i,1000);t+=8333;assert(f.step(t)==1);}int origin=f.out[0].x;for(int i=1;i<=5;++i){f.peak(26+i,299);t+=8333;assert(f.step(t)==1);}tail=f.out[0].x-origin;f.flat();assert(f.step(t+8333)==0);if(fixed)assert(tail>0);else assert(tail==0);++tests;}
 {F f;f.confirm();uint64_t t=9333;int origin=f.out[0].x;for(int i=0;i<60;++i){f.peak(20+(i%2),280);t+=8333;assert(f.step(t)==1);int drift=f.out[0].x-origin;if(drift<0)drift=-drift;if(drift>jitter)jitter=drift;}assert(jitter==0);++tests;}
 {F f;f.flat();f.m[20*NVT_COLUMNS+10]=6000;f.m[20*NVT_COLUMNS+40]=6000;assert(f.step(1000)==0&&f.step(9333)==2);int id1=f.out[0].tracking_id,id2=f.out[1].tracking_id;assert(id1!=id2);int origin1=f.out[0].x,origin2=f.out[1].x;uint64_t t=9333;for(int i=1;i<=8;++i){f.flat();f.m[20*NVT_COLUMNS+10+i]=5280;f.m[20*NVT_COLUMNS+40-i]=5280;t+=8333;assert(f.step(t)==2);bool a=false,b=false;for(int k=0;k<2;++k){a|=f.out[k].tracking_id==id1;b|=f.out[k].tracking_id==id2;}assert(a&&b);}multi_motion=0;for(int k=0;k<2;++k){int origin=f.out[k].tracking_id==id1?origin1:origin2;int delta=f.out[k].x-origin;multi_motion+=delta<0?-delta:delta;}if(fixed)assert(multi_motion>0);else assert(multi_motion==0);++tests;}
 {F f;f.confirm();uint64_t t=9333;const int values[]={220,221,229,260,280,299,300};for(int peak:values){f.peak(20,peak);t+=8333;assert(f.step(t)==1);}++tests;}
 std::printf("{\"mode\":\"%s\",\"tests\":%u,\"weak10_raw_motion\":%d,\"weak10_report_motion_before_up\":%d,\"weak10_max_lag\":%d,\"single_weak_report_before_up\":%d,\"strong_then_weak299_tail_displacement\":%d,\"weak_centroid50px_jitter_output\":%d,\"two_weak_contacts_total_motion\":%d}\n",argv[1],tests,short_raw,short_report,max_lag,single_report,tail,jitter,multi_motion);
}
