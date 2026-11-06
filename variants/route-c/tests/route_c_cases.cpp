#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
extern "C" {
void *baseline_create(void);
void baseline_destroy(void *);
int baseline_step(void *,const int16_t *,unsigned,nvt_contact *,int);
}
static unsigned passes;
static void pass(const char *name){++passes;std::printf("PASS %s\n",name);}
struct F {
    std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine engine{c.get()};
    int16_t m[NVT_NODES],decoded[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];unsigned counter=0;
    F(){nvt_touch_reset(c.get());flat();build(2);assert(engine.frame(raw,sizeof raw,0,decoded,out,NVT_SLOTS)==-1);}
    void flat(){for(auto &x:m)x=5000;}
    void node(int r,int col,int amount){m[r*NVT_COLUMNS+col]=(int16_t)(5000+amount);}
    void patch(int r=20,int col=20,int peak=1000){flat();addPatch(r,col,peak);}
    void addPatch(int r,int col,int peak=1000){node(r,col,peak);node(r,col+1,peak*3/5);node(r+1,col,peak/2);node(r+1,col+1,peak*2/5);}
    void build(unsigned type=4,unsigned data=0){
        std::memset(raw,0,sizeof raw);++counter;raw[259]=(uint8_t)counter;raw[260]=(uint8_t)(counter>>8);
        raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;
        raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;
        raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)data;
        std::memcpy(raw+321,m,sizeof m);
    }
    int frame(uint64_t now,unsigned data=0){build(4,data);return engine.frame(raw,sizeof raw,now,decoded,out,NVT_SLOTS);}
    int expire(uint64_t now){return engine.expire(now,out,NVT_SLOTS);}
    int step(uint64_t now,unsigned data=0){(void)expire(now);return frame(now,data);}
    unsigned active()const{unsigned n=0;for(const auto &x:c->slots)n+=x.active!=0;return n;}
};
int main(){
    {
        F f;f.patch();assert(f.step(1000)==1);const auto &s=f.c->slots[f.out[0].slot];
        assert(s.age==2 && s.born_us==1000 && s.last_observed_us==1000);
        assert(f.out[0].x==s.x && f.out[0].y==s.y && s.rx==s.x && s.ry==s.y);
        const int id=f.out[0].tracking_id;assert(f.step(9333)==1 && f.out[0].tracking_id==id);
        pass("strict_compact_strong_single_M_starts_at_actual_origin");
    }
    {
        F f;f.patch(20,20,599);assert(f.step(1000)==0);assert(f.active()==1 && f.c->slots[0].age==1);
        const int id=f.c->slots[0].tracking_id;assert(f.step(9333)==1 && f.out[0].tracking_id==id);
        F edge;edge.patch(20,20,600);assert(edge.step(1000)==1);
        pass("600_boundary_only_fast_path_below_gate_keeps_two_M_confirmation");
    }
    {
        F f;f.flat();f.node(20,20,12000);assert(f.step(1000)==0);assert(f.step(9333)==1);
        pass("arbitrarily_high_single_node_is_not_fast_confirmed");
    }
    {
        F f;f.flat();f.node(20,20,1000);f.node(20,21,500);f.node(20,22,300);
        assert(f.step(1000)==0);assert(f.active()==1 && f.c->slots[0].age==1);
        pass("one_dimensional_three_node_ridge_requires_confirmation");
    }
    {
        F f;f.flat();for(int r=-3;r<=3;++r)for(int col=-1;col<=1;++col)
            f.node(20+r,20+col,1000-70*(r<0?-r:r)-50*(col<0?-col:col));
        assert(f.step(1000)==0 && f.active()==1);
        pass("wide_seven_row_blob_does_not_pass_compact_gate");
    }
    {
        F f;f.flat();for(int r=-3;r<=3;++r)for(int col=-4;col<=4;++col)
            f.node(20+r,20+col,1000-30*(r<0?-r:r)-30*(col<0?-col:col));
        assert(f.step(1000)==0 && f.active()==0);
        pass("palm_area_is_still_rejected_before_fast_start");
    }
    {
        F f;f.patch(10,10);f.addPatch(30,45);assert(f.step(1000)==0 && f.active()==2);
        assert(f.step(9333)==2 && f.out[0].tracking_id!=f.out[1].tracking_id);
        pass("two_compact_blobs_never_bypass_confirmation");
    }
    {
        F f;f.patch();f.addPatch(20,22,800);assert(f.step(1000)==0);
        pass("current_frame_merged_ridge_is_not_a_single_unmerged_peak");
    }
    {
        F f;f.flat();f.node(20,20,500);assert(f.step(1000)==0);f.patch(10,45);
        assert(f.step(9333)==0 && f.active()==1);
        for(const auto &s:f.c->slots)if(s.active)assert(s.age==1);
        pass("entry_pending_slot_disables_fast_replacement_even_if_retired");
    }
    {
        F f;f.patch();assert(f.step(1000)==1);const int old=f.out[0].tracking_id;
        f.patch(10,45);assert(f.step(9333)==0 && f.active()==1);
        for(const auto &s:f.c->slots)if(s.active)assert(s.age==1 && s.tracking_id!=old);
        pass("entry_visible_slot_disables_fast_replacement_and_quarantines_ID");
    }
    {
        F f;f.patch();assert(f.step(1000)==1);const int id=f.out[0].tracking_id;
        f.addPatch(10,45);assert(f.step(9333)==1 && f.out[0].tracking_id==id && f.active()==2);
        assert(f.step(17666)==2);
        pass("new_second_finger_still_waits_for_second_observation");
    }
    {
        F f;f.flat();f.node(0,4,12000);f.node(32,20,12000);f.build(4,0x1d);
        auto before=std::make_unique<nvt_touch_core>();std::memcpy(before.get(),f.c.get(),sizeof(*before));
        assert(f.engine.frame(f.raw,sizeof f.raw,1000,f.decoded,f.out,NVT_SLOTS)==TouchEngine::SpecialP);
        assert(!std::memcmp(before.get(),f.c.get(),sizeof(*before)) && f.active()==0);
        f.patch();f.build(4,0x1d);assert(f.engine.frame(f.raw,sizeof f.raw,1000,f.decoded,f.out,NVT_SLOTS)==TouchEngine::SpecialP);
        assert(f.active()==0);
        pass("P_fake_anchor_and_compact_patterns_cannot_enter_fast_gate");
    }
    {
        F f;f.patch();assert(f.step(1000)==1);f.flat();assert(f.step(9333)==0 && f.active()==0);
        assert(f.c->ends[NVT_MISS_NONE]==1 && f.expire(200000)==-1);
        pass("observed_empty_M_releases_fast_contact_without_synthetic_hold");
    }
    {
        F f;f.patch();assert(f.step(1000)==1);const int old=f.out[0].tracking_id;
        for(uint64_t t=5167;t<101000;t+=4167)assert(f.step(t,0x1d)==TouchEngine::SpecialP);
        assert(f.expire(101000)==0 && f.c->observation_cancelled==1);
        assert(f.expire(101001)==-1);assert(f.frame(101001)==1 && f.out[0].tracking_id!=old);
        pass("P_only_policy_cancel_once_new_strong_M_gets_new_ID");
    }
    {
        F f;f.patch();assert(f.step(10000)==1);const int old=f.out[0].tracking_id;
        assert(f.expire(5000)==0 && f.c->clock_rebases==1);
        assert(f.frame(5001)==1 && f.out[0].tracking_id!=old);
        pass("clock_rollback_UP_is_not_resurrected_by_fast_start");
    }
    {
        F f;nvt_touch_reset(f.c.get());f.patch();
        for(unsigned i=0;i<5;++i)assert(f.frame(1000+i*8333)==-1 && f.active()==0);
        assert(!f.c->have_reference);
        pass("no_fast_start_before_reference_is_established");
    }
    {
        F f;void *old=baseline_create();assert(old);int16_t blank[NVT_NODES];for(auto &v:blank)v=5000;
        nvt_contact expected[NVT_SLOTS];assert(baseline_step(old,blank,2,expected,NVT_SLOTS)==-1);
        f.patch();for(unsigned i=0;i<4;++i){int n=nvt_touch_process(f.c.get(),f.m,4,f.out,NVT_SLOTS);
            int want=baseline_step(old,f.m,4,expected,NVT_SLOTS);assert(n==want);if(n)assert(!std::memcmp(f.out,expected,n*sizeof(expected[0])));}
        baseline_destroy(old);pass("legacy_API_high_confidence_shape_remains_exact_author_behavior");
    }
    std::printf("{\"status\":\"PASS_HOST_SYNTHETIC_NOT_HARDWARE\",\"route\":\"C-fast-confirm\",\"tests\":%u}\n",passes);
    return 0;
}