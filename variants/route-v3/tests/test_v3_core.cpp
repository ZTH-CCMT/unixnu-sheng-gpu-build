#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <cstdint>
struct Feed {
 std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine e{c.get()};
 int16_t m[NVT_NODES],decoded[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];unsigned seq=0;uint64_t now=0;
 Feed(){nvt_touch_reset(c.get());flat();packet(2);assert(e.frame(raw,sizeof raw,0,decoded,out,NVT_SLOTS)==-1);}
 void flat(){for(auto &v:m)v=5000;}
 void single(int r,int col,int a=1000){flat();m[r*NVT_COLUMNS+col]=(int16_t)(5000+a);}
 void blob(int r,int col,int a=1000){flat();addblob(r,col,a);}
 void addblob(int r,int col,int a=1000){m[r*NVT_COLUMNS+col]=(int16_t)(5000+a);m[r*NVT_COLUMNS+col+1]=(int16_t)(5000+a*3/4);m[(r+1)*NVT_COLUMNS+col]=(int16_t)(5000+a*2/3);m[(r+1)*NVT_COLUMNS+col+1]=(int16_t)(5000+a/2);}
 void packet(unsigned type=4,unsigned kind=0){std::memset(raw,0,sizeof raw);++seq;raw[259]=(uint8_t)seq;raw[260]=(uint8_t)(seq>>8);raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)kind;std::memcpy(raw+321,m,sizeof m);}
 int at(uint64_t t,unsigned kind=0){now=t;(void)e.expire(t,out,NVT_SLOTS);packet(4,kind);return e.frame(raw,sizeof raw,t,decoded,out,NVT_SLOTS);}
 nvt_slot &slot(int id){for(auto &s:c->slots)if(s.active&&s.tracking_id==id)return s;assert(false);return c->slots[0];}
 int down(int r=20,int col=20){blob(r,col);assert(at(1000)==1);return out[0].tracking_id;}
};
static unsigned passed;static void ok(const char *s){++passed;std::printf("PASS %s\n",s);}
int main(){std::setvbuf(stdout,nullptr,_IONBF,0);int weak_move=0,weak_turn=0,coherent_noise=0,tail=0;
 {Feed f;f.blob(20,20);assert(f.at(1000)==1);f.flat();assert(f.at(9333)==0);ok("qualified_compact_first_M_can_form_short_DOWN_then_real_empty_UP");}
 {Feed f;f.single(20,20);assert(f.at(1000)==0&&f.at(9333)==1);ok("isolated_strong_node_keeps_ordinary_two_M_confirmation");}
 {Feed f;int id=f.down();f.blob(20,21,280);assert(f.at(9333)==1&&f.out[0].tracking_id==id&&f.slot(id).last_filter_us==9333);int x=f.out[0].x;f.blob(21,21,280);assert(f.at(17666)==1&&f.slot(id).last_filter_us==17666);int y=f.out[0].y;f.blob(21,20,280);assert(f.at(25999)==1&&f.slot(id).last_filter_us==25999);weak_move=x;weak_turn=y;ok("spatial_weak_first_observation_and_right_angle_or_reversal_do_not_veto_filter");}
 {Feed f;int id=f.down();int old=f.out[0].x;f.flat();f.m[20*NVT_COLUMNS+20]=5280;f.m[21*NVT_COLUMNS+21]=5210;f.m[22*NVT_COLUMNS+22]=5180;assert(f.at(9333)==1&&f.slot(id).last_filter_us==1000&&f.out[0].x==old);ok("strict_collinear_weak_support_cannot_be_misread_as_two_dimensional");}
 {Feed f;int id=f.down();int old=f.out[0].x;f.flat();f.m[20*NVT_COLUMNS+20]=5280;f.m[20*NVT_COLUMNS+21]=5210;f.m[20*NVT_COLUMNS+22]=5180;assert(f.at(9333)==1&&f.slot(id).last_filter_us==1000&&f.out[0].x==old);ok("one_row_weak_ridge_cannot_unlock_spatial_follow");}
 {Feed f;int id=f.down(0,20);int old=f.out[0].x;f.flat();f.m[20]=5280;f.m[21]=5210;f.m[22]=5180;assert(f.at(9333)==1&&f.slot(id).last_filter_us==1000&&f.out[0].x==old);ok("edge_flag_is_not_an_automatic_trust_exception");}
 {Feed f;int id=f.down();nvt_slot old=f.slot(id);f.blob(25,40,6000);assert(f.at(9333,0x1d)==TouchEngine::SpecialP);assert(std::memcmp(&old,&f.slot(id),sizeof old)==0);ok("P_fake_high_compact_shape_never_reaches_fast_or_weak_profile");}
 {Feed f;f.down();f.blob(20,35);assert(f.at(9333)==0&&f.at(17666)==1);ok("active_entry_cannot_gain_single_M_replacement_after_far_retirement");}
 {Feed f;f.flat();f.addblob(10,10);f.addblob(20,40);assert(f.at(1000)==0&&f.at(9333)==2);assert(f.out[0].tracking_id!=f.out[1].tracking_id);ok("multiple_peaks_cannot_use_isolated_fast_start_and_keep_distinct_IDs");}
 {Feed f;int id=f.down();assert(f.e.expire(101000,f.out,NVT_SLOTS)==0&&f.c->observation_cancelled==1);f.blob(20,20,280);assert(f.at(109333)==0);(void)id;ok("no_M100ms_still_cancels_and_weak_blob_cannot_create_DOWN");}
 {Feed f;int id=f.down();f.blob(20,20,280);assert(f.at(9333)==1);assert(f.e.expire(100,f.out,NVT_SLOTS)==0&&f.c->clock_rebases==1);f.blob(20,20);assert(f.at(200)==1&&f.out[0].tracking_id!=id&&f.slot(f.out[0].tracking_id).last_filter_us==200);ok("clock_rollback_does_not_reuse_old_filter_state_or_ID");}
 {Feed f;int id=f.down();int origin=f.out[0].x;uint64_t t=1000;for(int i=0;i<20;++i){f.blob(20,20+(i%2),280);t+=8333;assert(f.at(t)==1&&f.out[0].tracking_id==id);int d=f.out[0].x-origin;if(d<0)d=-d;if(d>coherent_noise)coherent_noise=d;}assert(coherent_noise>0);ok("documented_counterexample_coherent_2D_noise_CAN_pass_spatial_profile");}
 {Feed f;f.down();uint64_t t=1000;for(int i=1;i<=5;++i){f.blob(20,20+i,1000);t+=8333;assert(f.at(t)==1);}int old=f.out[0].x;for(int i=1;i<=5;++i){f.blob(20,25+i,280);t+=8333;assert(f.at(t)==1);}tail=f.out[0].x-old;assert(tail>0);f.flat();assert(f.at(t+8333)==0);ok("documented_counterexample_coherent_weak_tail_CAN_move_until_empty_M");}
 std::printf("{\"status\":\"PASS_V3_REAL_CORE_SYNTHETIC_NOT_HARDWARE\",\"tests\":%u,\"weak_first_report_x\":%d,\"weak_turn_report_y\":%d,\"coherent_2D_noise_peak_motion_units\":%d,\"weak_tail_motion_units\":%d,\"contact_bytes\":%zu,\"slot_bytes\":%zu,\"Core_bytes\":%zu}\n",passed,weak_move,weak_turn,coherent_noise,tail,sizeof(nvt_contact),sizeof(nvt_slot),sizeof(nvt_touch_core));}
