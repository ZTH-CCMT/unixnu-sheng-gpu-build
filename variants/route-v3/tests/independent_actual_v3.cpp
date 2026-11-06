// SPDX-License-Identifier: Apache-2.0
#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <algorithm>
struct Feed {
 std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine e{c.get()};
 int16_t m[NVT_NODES],decoded[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];unsigned seq=0;
 Feed(){nvt_touch_reset(c.get());flat();packet(2,0);assert(e.frame(raw,sizeof raw,0,decoded,out,NVT_SLOTS)==-1);}
 void flat(){for(auto &v:m)v=5000;}
 void node(int r,int col,int a){assert(r>=0&&r<40&&col>=0&&col<60);m[r*60+col]=(int16_t)(5000+a);}
 void point(int r,int col,int a=1000){flat();node(r,col,a);}
 void compact(int r,int col,int a=299){flat();node(r,col,a);node(r,col+1,a*3/5);node(r+1,col,a*3/5);node(r+1,col+1,a*2/5);}
 void line(int r,int col,bool diagonal=false){flat();node(r,col,299);node(r+(diagonal?1:0),col+1,200);node(r+(diagonal?2:0),col+2,100);}
 void packet(unsigned type=4,unsigned special=0){std::memset(raw,0,sizeof raw);++seq;raw[259]=(uint8_t)seq;raw[260]=(uint8_t)(seq>>8);raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)special;std::memcpy(raw+321,m,sizeof m);}
 int at(uint64_t t,unsigned special=0){(void)e.expire(t,out,NVT_SLOTS);packet(4,special);return e.frame(raw,sizeof raw,t,decoded,out,NVT_SLOTS);}
 int down(int r=20,int col=20){point(r,col);assert(at(1000)==0);assert(at(9333)==1);return out[0].tracking_id;}
 nvt_slot &slot(int id){for(auto &s:c->slots)if(s.active&&s.tracking_id==id)return s;assert(false);return c->slots[0];}
};
static unsigned checks;static void ok(const char *name,int motion=0){++checks;std::printf("{\"case\":\"%s\",\"motion_units\":%d}\n",name,motion);}
int main(){std::setvbuf(stdout,nullptr,_IONBF,0);
 {Feed f;int id=f.down(),x=f.out[0].x;f.line(20,21);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.out[0].x==x&&f.slot(id).last_filter_us==9333&&f.slot(id).last_observed_us==17666);ok("thin_one_row_weak_freezes_output_not_observation_clock");}
 {Feed f;int id=f.down(0,20),x=f.out[0].x;f.line(0,21);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.out[0].x==x&&f.slot(id).last_filter_us==9333);ok("thin_sensor_edge_three_node_run_no_exception");}
 {Feed f;int id=f.down(),x=f.out[0].x,y=f.out[0].y;f.line(20,20,true);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.out[0].x==x&&f.out[0].y==y&&f.slot(id).last_filter_us==9333);ok("diagonal_collinear_weak_support_stays_frozen");}
 {Feed f;int id=f.down();f.compact(20,21);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==17666);const int before=f.out[0].x;f.compact(20,22);assert(f.at(25999)==1&&f.slot(id).last_filter_us==25999&&f.out[0].x>before);const int turn_y=f.out[0].y;f.compact(21,22);assert(f.at(34332)==1&&f.slot(id).last_filter_us==34332&&f.out[0].y>turn_y);ok("compact_weak_right_angle_no_direction_veto",f.out[0].y-turn_y);}
 {Feed f;int id=f.down();uint64_t t=9333;const int p[][2]={{20,21},{21,21},{21,20},{20,20},{20,21},{21,21},{21,20},{20,20}};for(auto &v:p){t+=8333;f.compact(v[0],v[1]);assert(f.at(t)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==t);}ok("compact_weak_square_every_measurement_updates_filter_clock");}
 {Feed f;int id=f.down();f.compact(20,21);assert(f.at(17666)==1);f.compact(20,20);assert(f.at(25999)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==25999);ok("compact_weak_reversal_is_not_suppressed");}
 {Feed f;int id=f.down(),origin=f.out[0].x;uint64_t t=9333;int maximum=origin;for(int i=1;i<=20;++i){t+=8333;f.compact(20,20+i);assert(f.at(t)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==t);maximum=std::max(maximum,f.out[0].x);}assert(maximum>origin+1000);ok("KNOWN_LIMIT_coherent_compact2D_weak_noise_or_tail_can_move",maximum-origin);}
 {Feed f;f.compact(20,20,600);assert(f.at(1000)==1&&f.c->slots[f.out[0].slot].age==2);const int id=f.out[0].tracking_id;f.flat();assert(f.at(9333)==0);f.compact(20,20,600);assert(f.at(17666)==1&&f.out[0].tracking_id!=id);ok("strict_compact600_singleM_fasttap_UP_fresh_ID");}
 {Feed f;f.compact(20,20,599);assert(f.at(1000)==0&&f.at(9333)==1);ok("below600_compact_uses_ordinary_twoM_path");}
 {Feed f;f.point(20,20,600);assert(f.at(1000)==0);f.flat();assert(f.at(9333)==0);ok("single_node600_never_fast_DOWN");}
 {Feed f;f.flat();f.node(20,20,600);f.node(20,21,200);f.node(21,20,200);assert(f.at(1000)==0&&f.at(9333)==1);ok("fast_support_counts_absolute220_not_shape_floor99");}
 {Feed f;f.compact(20,20,299);assert(f.at(1000)==0&&f.at(9333)==0);ok("2D_weak_never_creates_new_DOWN");}
 {Feed f;int id=f.down();f.compact(20,20);assert(f.at(17666)==1);const nvt_slot before=f.slot(id);f.compact(30,50,2000);assert(f.at(21000,0x1d)==TouchEngine::SpecialP);assert(std::memcmp(&before,&f.slot(id),sizeof before)==0);ok("real_P_classifier_preserves_slot_filter_raw_and_observation");}
 {Feed f;int id=f.down(),origin=f.out[0].x;uint64_t t=9333;for(int i=0;i<20;++i){t+=8333;f.line(20,20+(i&1));assert(f.at(t)==1&&f.out[0].tracking_id==id&&f.out[0].x==origin&&f.slot(id).last_filter_us==9333&&f.slot(id).last_observed_us==t);}f.compact(20,21,1000);t+=8333;assert(f.at(t)==1&&f.slot(id).last_filter_us==t);ok("rejected_shape_does_not_refresh_filter_clock_strong_recovery_uses_full_gap",f.out[0].x-origin);}
 {Feed f;int id=f.down();f.compact(20,20);assert(f.at(17666)==1);f.flat();assert(f.at(25999)==0&&(f.c->retired_ids&(1u<<id)));f.compact(20,20,299);assert(f.at(34332)==0);ok("empty_M_UP_weak_cannot_revive_retired_ID");}
 {Feed f;int id=f.down();f.compact(20,20);int count=0;for(int r=2;r<=14&&count<26;r+=3)for(int col=2;col<=23&&count<26;col+=3){f.node(r,col,101);++count;}assert(count==26&&f.at(17666)==1&&f.out[0].tracking_id==id&&f.c->peak_overflows>0&&f.slot(id).last_filter_us==9333);ok("real_peak_overflow_disables_weak_shape_follow");}
  {Feed f;int id=f.down();f.compact(20,21,220);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==17666);ok("exact220_spatial_weak_boundary_acceptance_is_explicit");}
 {Feed f;int id=f.down();f.compact(20,20,219);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==9333&&f.slot(id).last_observed_us==9333&&f.slot(id).missed==1);ok("below220_is_dropout_not_spatial_weak_follow");}
 {Feed f;f.flat();f.node(20,20,600);f.node(20,21,220);f.node(21,20,220);assert(f.at(1000)==1);ok("fast_support_exact220_boundary_included");}
  {Feed f;f.point(20,20,300);assert(f.at(1000)==0);f.compact(20,20,299);assert(f.at(9333)==1);const int id=f.out[0].tracking_id;assert(f.slot(id).age==2&&f.slot(id).last_filter_us==1000);assert(f.at(17666)==1&&f.slot(id).last_filter_us==17666);ok("first_visible_weak_uses_seed_then_follow_requires_previously_visible");}
 {Feed f;f.compact(20,20,600);assert(nvt_touch_process(f.c.get(),f.m,4,f.out,NVT_SLOTS)==0);assert(nvt_touch_process(f.c.get(),f.m,4,f.out,NVT_SLOTS)==1);const int id=f.out[0].tracking_id,x=f.out[0].x;f.compact(20,21,299);assert(nvt_touch_process(f.c.get(),f.m,4,f.out,NVT_SLOTS)==1&&f.out[0].tracking_id==id&&f.out[0].x==x&&f.slot(id).last_filter_us==0);ok("legacy_keeps_twoM_start_and_weak_freeze");}
 std::printf("{\"status\":\"PASS_ACTUAL_V3_CORE_ENGINE_SYNTHETIC_NOT_HARDWARE\",\"checks\":%u,\"slot_bytes\":%zu,\"Core_bytes\":%zu}\n",checks,sizeof(nvt_slot),sizeof(nvt_touch_core));
}
