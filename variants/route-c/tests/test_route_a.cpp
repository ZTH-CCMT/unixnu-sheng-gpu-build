#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <initializer_list>
extern "C" {
void route_a_probe(const nvt_touch_core*,const nvt_contact*,int,int*,long*);
void parent_ag_assign(const nvt_touch_core*,const nvt_contact*,int,int*);
void ag_nvt_touch_reset(nvt_touch_core*);
int ag_nvt_touch_expire(nvt_touch_core*,uint64_t,nvt_contact*,int);
int ag_nvt_touch_process_timed(nvt_touch_core*,const int16_t*,unsigned,uint64_t,nvt_contact*,int);
}
static unsigned passed;
static void pass(const char *name){++passed;std::printf("PASS %s\n",name);}
static void activate(nvt_touch_core &c,int s,int x,int y,int dx=0,int dy=0,int age=3){
 auto &p=c.slots[s];p={};p.active=1;p.tracking_id=s+1;p.age=age;p.x=p.rx=x;p.y=p.ry=y;p.fx=16L*x;p.fy=16L*y;p.dx=dx;p.dy=dy;p.last_interval_us=8333;p.last_observed_us=75000;p.born_us=50000;
}
static std::unique_ptr<nvt_touch_core> state(){auto c=std::make_unique<nvt_touch_core>();nvt_touch_reset(c.get());c->timed_enabled=1;c->clock_valid=1;c->now_us=100000;activate(*c,0,11490,10560,1010,0);return c;}
static nvt_contact point(int x,int y,int peak=1000){nvt_contact c={};c.x=x;c.y=y;c.peak=peak;return c;}
static void probe(const nvt_touch_core &c,const nvt_contact *p,int n,int *match,long *d){route_a_probe(&c,p,n,match,d);}
struct Pair {
 std::unique_ptr<nvt_touch_core> a{new nvt_touch_core},old{new nvt_touch_core};TouchEngine engine{a.get()};
 int16_t matrix[NVT_NODES]{},decoded[NVT_NODES]{};uint8_t raw[NVT_THP_FRAME_LEN]{};nvt_contact ao[NVT_SLOTS]{},bo[NVT_SLOTS]{};int an=-1,bn=-1;
 Pair(){nvt_touch_reset(a.get());ag_nvt_touch_reset(old.get());flat();frame(0,2);}
 void flat(){for(auto &v:matrix)v=5000;}
 void peak(int row,int col,int amount=1000){flat();matrix[row*NVT_COLUMNS+col]=(int16_t)(5000+amount);}
 void frame(uint64_t now,unsigned type=4,unsigned dataType=0){
  static unsigned counter;std::memset(raw,0,sizeof raw);++counter;raw[259]=(uint8_t)counter;raw[260]=(uint8_t)(counter>>8);
  raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)dataType;
  std::memcpy(raw+321,matrix,sizeof matrix);(void)engine.expire(now,ao,NVT_SLOTS);an=engine.frame(raw,sizeof raw,now,decoded,ao,NVT_SLOTS);
  (void)ag_nvt_touch_expire(old.get(),now,bo,NVT_SLOTS);bn=dataType==0x1d ? TouchEngine::SpecialP : ag_nvt_touch_process_timed(old.get(),matrix,type,now,bo,NVT_SLOTS);
 }
 int confirm_move(){peak(20,20);frame(1000);assert(an==0&&bn==0);peak(20,22);frame(9333);assert(an==1&&bn==1);assert(ao[0].tracking_id==bo[0].tracking_id);return ao[0].tracking_id;}
 void trace(const char*name){std::printf("TRACE %s old_n=%d new_n=%d old_id=%d new_id=%d old_far=%lu new_far=%lu\n",name,bn,an,bn>0?bo[0].tracking_id:0,an>0?ao[0].tracking_id:0,old->far_retired,a->far_retired);}
};
int main(){
 std::setvbuf(stdout,nullptr,_IONBF,0);
 {
  Pair f;const int id=f.confirm_move();f.peak(20,22);f.frame(34333);f.trace("stop_101px_then_25ms");
  assert(f.an==1&&f.ao[0].tracking_id==id&&f.a->far_retired==0);assert(f.bn==0&&f.old->far_retired==1);
  pass("real_Core_Engine_old_AG_stop_failure_new_A_keeps_same_id");
 }
 {
  Pair f;const int id=f.confirm_move();f.peak(20,28);f.frame(34333);f.trace("fast_continue_300px_25ms");
  assert(f.an==1&&f.bn==1&&f.ao[0].tracking_id==id&&f.bo[0].tracking_id==id);assert(!std::memcmp(f.ao,f.bo,sizeof(nvt_contact)));pass("fast_continuation_matches_parent_AG_output");
 }
 {
  Pair f;f.confirm_move();f.peak(20,22,299);f.frame(34333);f.trace("weak_stop_299_25ms");
  assert(f.an==f.bn&&f.an==0&&f.a->far_retired==f.old->far_retired);pass("weak_matrix_stop_output_matches_parent_AG");
 }
 {
  auto c=state();nvt_contact p=point(11390,10560);int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);parent_ag_assign(c.get(),&p,1,oldmatch);
  assert(match[0]==0&&oldmatch[0]==-1&&d[4]==0&&d[6]<d[7]);assert(d[0]-c->slots[0].x>2000&&d[2]-c->slots[0].x==2000);pass("stop_jitter_fallback_works_when_prediction_gate_rejects");
 }
 {
  auto c=state();nvt_contact p=point(11390,10660);int match[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);assert(match[0]==0&&d[4]==0);pass("acute_turn_near_last_raw_point_not_far_retired");
 }
 {
  auto c=state();c->slots[0].dy=1010;nvt_contact p=point(11490,10560);int match[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);
  long x=d[2]-c->slots[0].x,y=d[3]-c->slots[0].y;assert(x*x+y*y<=4000000L&&x>0&&y>0);assert(x!=2000&&y!=2000);assert(match[0]==0);pass("Euclidean_vector_cap_not_independent_axis_clip");
 }
 {
  auto c=state();nvt_contact p[2]={point(11490,10560),point(14490,10560)};int match[NVT_SLOTS];long d[8];probe(*c,p,2,match,d);assert(d[5]==1&&match[0]==-1);pass("old_location_plus_predicted_location_is_identity_ambiguity");
 }
 {
  auto c=state();nvt_contact p[2]={point(11390,10560),point(11590,10560)};int match[NVT_SLOTS];long d[8];probe(*c,p,2,match,d);assert(d[5]==1&&match[0]==-1);pass("two_local_strong_alternatives_cannot_sneak_through_capped_cost");
 }
 {
  for(int age:{1,3}){auto c=state();activate(*c,1,11590,10560,0,0,age);nvt_contact p=point(11390,10560);int match[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);assert(d[5]==1&&match[0]==-1);assert(match[1]==0);}
  pass("active_and_hidden_competitors_prevent_fallback_ID_takeover");
 }
 {
  auto c=state();nvt_contact p=point(11390,10560,299);int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);parent_ag_assign(c.get(),&p,1,oldmatch);assert(d[4]==-1&&match[0]==oldmatch[0]&&match[0]==-1);
  p.peak=300;probe(*c,&p,1,match,d);assert(d[4]==0&&match[0]==0);pass("weak299_no_new_rescue_strong300_boundary");
 }
 {
  auto c=state();c->slots[0].missed=1;nvt_contact p=point(11390,10560);int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);parent_ag_assign(c.get(),&p,1,oldmatch);assert(d[4]==-1&&match[0]==oldmatch[0]&&match[0]==-1);assert(d[0]==d[2]&&d[1]==d[3]);pass("missed_REJOIN_center_and24px_gate_unchanged");
 }
 {
  auto c=state();nvt_contact p=point(11390,10560);int match[NVT_SLOTS];long d[8];c->now_us=100001;probe(*c,&p,1,match,d);assert(d[4]==-1&&match[0]==-1);c->now_us=100000;probe(*c,&p,1,match,d);assert(d[4]==0&&match[0]==0);pass("experimental25ms_rescue_boundary_not100ms_lifetime_change");
 }
 {
  auto c=state();nvt_contact p=point(11490-240,10560);int match[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);assert(d[4]==0&&d[6]==2*240L*240&&d[6]<d[7]);p.x--;probe(*c,&p,1,match,d);assert(d[4]==-1&&match[0]==-1);pass("24px_inclusive_rescue_penalty_below_dummy_boundary");
 }
 {
  auto c=state();c->slots[0].dx=0;nvt_contact p=point(13490,10560);int match[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);assert(d[6]==4000000L&&d[7]==4000000L);assert(d[4]==-1);pass("original_radius_equality_and_dummy_cost_not_globally_relaxed");
 }
 {
  auto c=state();activate(*c,0,5000,9000,500,0);activate(*c,1,22000,9000,500,0);c->now_us=83333;nvt_contact p[2]={point(5500,9000),point(22500,9000)};int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,p,2,match,d);parent_ag_assign(c.get(),p,2,oldmatch);assert(match[0]==0&&match[1]==1&&match[0]==oldmatch[0]&&match[1]==oldmatch[1]);pass("ordinary_two_finger_drag_one_to_one_matches_AG");
 }
 {
  auto c=state();activate(*c,0,10000,9000,500,0);activate(*c,1,11000,9000,-500,0);c->now_us=83333;nvt_contact p[2]={point(10500,8900),point(10500,9100)};int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,p,2,match,d);parent_ag_assign(c.get(),p,2,oldmatch);assert(match[0]!=match[1]&&match[0]>=0&&match[1]>=0);assert(match[0]==oldmatch[0]&&match[1]==oldmatch[1]);pass("normal_crossing_tie_keeps_parent_global_assignment_without_fallback");
 }
 {
  auto c=state();for(int i=0;i<4;++i)activate(*c,i,4000+6000*i,9000,1500,0);nvt_contact p[4]={point(4000,9000),point(10000,9000),point(16000,9000),point(22000,9000)};int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,p,4,match,d);parent_ag_assign(c.get(),p,4,oldmatch);for(int i=0;i<4;++i)assert(match[i]==i&&match[i]==oldmatch[i]);pass("four_finger_prediction_disabled_path_unchanged");
 }
 {
  for(int sign:{-1,1}){auto c=state();auto &q=c->slots[0];q.x=sign>0?30479:0;q.y=sign>0?20319:0;q.dx=sign*30479;q.dy=sign*20319;q.last_interval_us=1;nvt_contact p=point(q.x-sign*100,q.y-sign*100);int match[NVT_SLOTS];long d[8];probe(*c,&p,1,match,d);long x=d[2]-q.x,y=d[3]-q.y;assert(x*x+y*y<=4000000L&&d[4]==0&&match[0]==0);}
  pass("valid_extreme_axis_delta_interval1us_signed_norm_and_cost_bounds");
 }
 {
  unsigned seed=0x51a772u;auto next=[&](){seed=1664525u*seed+1013904223u;return seed;};
  for(unsigned k=0;k<1000;++k){auto c=state();int n=1+(int)(next()%3);c->now_us=83333;nvt_contact p[3];for(int i=0;i<n;++i){int dx=(int)(next()%1401)-700,dy=(int)(next()%1401)-700;activate(*c,i,5000+9500*i,10000,dx,dy);p[i]=point(c->slots[i].x+dx+(int)(next()%101)-50,c->slots[i].y+dy+(int)(next()%101)-50);}int match[NVT_SLOTS],oldmatch[NVT_SLOTS];long d[8];probe(*c,p,n,match,d);parent_ag_assign(c.get(),p,n,oldmatch);for(int i=0;i<n;++i)assert(match[i]==oldmatch[i]&&match[i]>=0);}
  pass("1000_regular_one_to_three_finger_assignment_cases_match_parent_AG");
 }
 {
  Pair f;f.peak(20,20);f.frame(1000);f.frame(9333);assert(f.an==1);int id=f.ao[0].tracking_id;f.flat();f.frame(17666);assert(f.an==0);f.frame(20000,4,0x1d);assert(f.an==TouchEngine::SpecialP&&!f.a->slots[0].active);f.peak(20,20);f.frame(25000);assert(f.an==0);f.frame(33333);assert(f.an==1&&f.ao[0].tracking_id!=id);pass("real_empty_M_UP_and_special_P_never_revive_retired_ID");
 }
 {
  Pair f;f.peak(20,20);f.frame(1000);f.frame(9333);assert(f.an==1);int id=f.ao[0].tracking_id;f.frame(109333,4,0x1d);assert(f.an==TouchEngine::SpecialP&&f.a->observation_cancelled==1);f.frame(110000);assert(f.an==0);f.frame(118333);assert(f.an==1&&f.ao[0].tracking_id!=id);pass("100ms_observation_cancellation_remains_unfixed_and_reconfirms");
 }
 std::printf("{\"status\":\"PASS_HOST_SYNTHETIC_NOT_HARDWARE\",\"route\":\"A\",\"route_tests\":%u}\n",passed);
}
