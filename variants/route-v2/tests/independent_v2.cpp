#include "TouchEngine.h"
#include "OneEuroFilter.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <cmath>
#include <cstddef>
struct Feed {
 std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine e{c.get()};
 int16_t m[NVT_NODES],d[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];unsigned seq=0;
 Feed(){nvt_touch_reset(c.get());flat();packet(2,0);assert(e.frame(raw,sizeof raw,0,d,out,NVT_SLOTS)==-1);}
 void flat(){for(auto &v:m)v=5000;}
 void point(int row,int col,int amplitude=1000){flat();m[row*NVT_COLUMNS+col]=(int16_t)(5000+amplitude);}
 void packet(unsigned type=4,unsigned special=0){std::memset(raw,0,sizeof raw);++seq;raw[259]=(uint8_t)seq;raw[260]=(uint8_t)(seq>>8);raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)special;std::memcpy(raw+321,m,sizeof m);}
 int at(uint64_t t,unsigned special=0){(void)e.expire(t,out,NVT_SLOTS);packet(4,special);return e.frame(raw,sizeof raw,t,d,out,NVT_SLOTS);}
 int down(){point(20,20);assert(at(1000)==0);assert(at(9333)==1);return out[0].tracking_id;}
 nvt_slot &slot(int id){for(auto &s:c->slots)if(s.active&&s.tracking_id==id)return s;assert(false);return c->slots[0];}
};
static unsigned passed;static void ok(const char *s){++passed;std::printf("PASS %s\n",s);}
int main(){
 std::setvbuf(stdout,nullptr,_IONBF,0);
 {Feed f;int id=f.down(),origin=f.out[0].x;f.point(20,21,280);assert(f.at(17666)==1&&f.out[0].tracking_id==id&&f.out[0].x==origin);assert(f.slot(id).last_observed_us==17666&&f.slot(id).last_filter_us==9333);f.point(20,22,280);assert(f.at(25999)==1&&f.out[0].tracking_id==id&&f.out[0].x>origin);assert(f.slot(id).last_filter_us==25999);ok("first_untrusted_weak_skips_filter_clock_then_coherent_motion_updates_same_ID");}
 {Feed f;int id=f.down();f.point(20,21,280);assert(f.at(17666)==1);f.point(20,22,280);assert(f.at(25999)==1);int before=f.out[0].x;f.point(20,21,280);assert(f.at(34332)==1&&f.out[0].x==before&&f.slot(id).last_filter_us==25999);f.point(20,20,280);assert(f.at(42665)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==42665);ok("reversal_first_observation_not_accepted_later_consistent_return_keeps_ID");}
 {Feed f;int id=f.down();f.point(20,21,280);assert(f.at(17666)==1);f.point(20,22,280);assert(f.at(25999)==1);int x=f.out[0].x,y=f.out[0].y;f.point(21,22,280);assert(f.at(34332)==1&&f.out[0].x==x&&f.out[0].y==y&&f.slot(id).last_filter_us==25999);f.point(22,22,280);assert(f.at(42665)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==42665);ok("right_angle_first_observation_skips_filter_then_new_direction_recovers");}
 {Feed f;int id=f.down();f.point(20,21,280);assert(f.at(17666)==1);nvt_slot before=f.slot(id);f.point(33,50,6500);assert(f.at(21000,0x1d)==TouchEngine::SpecialP);assert(std::memcmp(&before,&f.slot(id),sizeof before)==0);f.point(20,22,280);assert(f.at(25999)==1&&f.slot(id).last_filter_us==25999);ok("real_classifier_P_never_mutates_slot_gate_raw_or_either_clock");}
 {Feed f;int id=f.down();f.point(20,21,280);assert(f.at(17666)==1);f.point(20,22,280);assert(f.at(50000)==1&&f.slot(id).last_filter_us==9333);f.point(20,23,280);assert(f.at(58333)==1&&f.slot(id).last_filter_us==9333);f.point(20,24,280);assert(f.at(66666)==1&&f.slot(id).last_filter_us==66666);ok("gap_over25ms_requires_new_weak_evidence_pair_before_applying");}
 {Feed f;int id=f.down();f.point(20,20,280);assert(f.at(17666)==1);f.point(20,20,219);assert(f.at(25999)==1&&f.slot(id).missed==1);f.point(20,20,280);assert(f.at(34332)==1&&f.slot(id).last_filter_us==9333);assert(f.at(42665)==1&&f.slot(id).last_filter_us==9333);assert(f.at(50998)==1&&f.slot(id).last_filter_us==50998);ok("real_unmatched_M_forces_weak_reacquisition_not_immediate_resurrection");}
 {Feed f;int id=f.down();f.point(20,21,280);assert(f.at(17666)==1);f.flat();assert(f.at(25999)==0);f.point(20,20);assert(f.at(34332)==0&&f.at(42665)==1);int newer=f.out[0].tracking_id;assert(newer!=id&&f.slot(newer).last_filter_us==42665&&f.slot(newer).weak_observed==0);f.point(20,21,280);assert(f.at(50998)==1&&f.slot(newer).last_filter_us==42665);ok("empty_M_UP_then_fresh_ID_seed_has_no_previous_gate_or_filter_clock");}
 {Feed f;int id=f.down(),origin=f.out[0].x;OneEuroFilter oracle(120,1,.0015,1);oracle.filter(origin,.001);oracle.filter(origin,.009333);uint64_t t=9333;for(unsigned i=1;i<=70;++i){t+=8333;f.point(20,20+(i&1),280);assert(f.at(t)==1&&f.out[0].tracking_id==id&&f.out[0].x==origin&&f.slot(id).last_filter_us==9333&&f.slot(id).last_observed_us==t);}t+=8333;f.point(20,21,1000);assert(f.at(t)==1&&f.out[0].tracking_id==id);const double target=oracle.filter(f.slot(id).x,(double)t/1000000.0);double error=std::fabs(target-f.out[0].x);assert(error<=2.0&&f.slot(id).last_filter_us==t);std::printf("{\"kind\":\"long_skipped_weak_recovery\",\"filter_interval_us\":%llu,\"observation_interval_us\":%llu,\"oracle_x\":%.9f,\"reported_x\":%d,\"error_units\":%.9f}\n",(unsigned long long)(t-9333),(unsigned long long)f.slot(id).last_interval_us,target,f.out[0].x,error);ok("rejected_weak_stream_keeps_filter_time_then_strong_recovery_matches_public_reference");}
 {Feed f;int id=f.down();f.point(20,20,280);assert(f.at(17666)==1&&f.slot(id).last_filter_us==9333);assert(f.at(25999)==1&&f.slot(id).last_filter_us==25999);assert(f.e.expire(125999,f.out,NVT_SLOTS)==0&&f.c->observation_cancelled==1);f.point(20,20,280);assert(f.at(134332)==0);f.point(20,20,1000);assert(f.at(142665)==0&&f.at(150998)==1);auto &fresh=f.slot(f.out[0].tracking_id);assert(fresh.born_us==142665&&fresh.last_filter_us==150998&&fresh.weak_observed==0);ok("stationary_weak_pair_may_apply_but100ms_noM_cancels_and_weak_cannot_create_DOWN");}
 {Feed f;int id=f.down();f.point(20,21,280);assert(f.at(17666)==1);assert(f.e.expire(100,f.out,NVT_SLOTS)==0&&f.c->clock_rebases==1);f.point(20,20);assert(f.at(200)==0&&f.at(8533)==1&&f.out[0].tracking_id!=id);auto &s=f.slot(f.out[0].tracking_id);assert(s.last_filter_us==8533&&s.weak_observed==0);ok("clock_rollback_retires_old_ID_and_reinitializes_gate_and_filter_timestamp");}
 std::printf("{\"status\":\"PASS_INDEPENDENT_V2_HOST_ONLY\",\"tests\":%u,\"slot_bytes\":%zu,\"Core_bytes\":%zu,\"contact_bytes\":%zu,\"timed_enabled_offset\":%zu}\n",passed,sizeof(nvt_slot),sizeof(nvt_touch_core),sizeof(nvt_contact),offsetof(nvt_touch_core,timed_enabled));
}
