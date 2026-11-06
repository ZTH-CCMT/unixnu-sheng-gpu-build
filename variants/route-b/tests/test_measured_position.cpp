#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <set>
#include <cstdint>

static unsigned passes;
static void pass(const char *name){++passes;std::printf("PASS %s\n",name);}
static int rawx(int col){return nvt_touch_map_edge_axis(nvt_touch_column_center(col)*NVT_SUPER_RESOLUTION,NVT_LONG_AXIS_MAX,0);}
struct Fixture {
    std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine engine{c.get()};
    int16_t m[NVT_NODES],decoded[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];
    unsigned counter=0;
    Fixture(){nvt_touch_reset(c.get());for(auto &v:m)v=5000;build(2,0);assert(engine.frame(raw,sizeof raw,0,decoded,out,NVT_SLOTS)==-1);}
    void flat(){std::memcpy(m,c->reference,sizeof m);}
    void add(int row,int col,int amount=1000){m[row*NVT_COLUMNS+col]=(int16_t)(m[row*NVT_COLUMNS+col]+amount);}
    void peak(int row,int col,int amount=1000){flat();add(row,col,amount);}
    void pair(int rowA,int colA,int rowB,int colB){flat();add(rowA,colA);add(rowB,colB);}
    void build(unsigned type=4,unsigned dt=0){
        std::memset(raw,0,sizeof raw);++counter;raw[259]=(uint8_t)counter;raw[260]=(uint8_t)(counter>>8);
        raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;
        raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;
        raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)dt;
        std::memcpy(raw+321,m,sizeof m);
    }
    int frame(uint64_t now,unsigned dt=0){build(4,dt);return engine.frame(raw,sizeof raw,now,decoded,out,NVT_SLOTS);}
    int expire(uint64_t now){return engine.expire(now,out,NVT_SLOTS);}
    int step(uint64_t now,unsigned dt=0){const int e=expire(now);(void)e;return frame(now,dt);}
    int confirm(int row=20,int col=20){peak(row,col);assert(step(1000)==0);assert(step(9333)==1);return out[0].tracking_id;}
    const nvt_slot *slot(int id)const {for(const auto &s:c->slots)if(s.active && s.tracking_id==id)return &s;return nullptr;}
    // Construct an ordinary, connected two-node blob with an exact interior
    // weighted-centroid x; this changes only the synthetic sensor input.
    void targetX(int row,int target){
        for(int col=0;col+1<NVT_COLUMNS;++col){
            const int x0=nvt_touch_column_center(col)*NVT_SUPER_RESOLUTION;
            const int x1=nvt_touch_column_center(col+1)*NVT_SUPER_RESOLUTION;
            if(target<x0 || target>x1)continue;
            for(int side=0;side<2;++side)for(int a=300;a<=1000;++a){
                const int left=side? a:1000,right=side?1000:a;
                const int wl=left-300,wr=right-300,sum=wl+wr;
                const int x=(x0*wl+x1*wr+sum/2)/sum;
                if(nvt_touch_map_edge_axis(x,NVT_LONG_AXIS_MAX,0)!=target)continue;
                flat();add(row,col,left);add(row,col+1,right);return;
            }
        }
        assert(false && "synthetic exact centroid not constructible");
    }
};
static void one(const Fixture &f,int n,int id){assert(n==1);assert(f.out[0].tracking_id==id);assert(f.slot(id));}
static void unique(const Fixture &f,int n){std::set<int> ids;for(int i=0;i<n;++i){assert(f.out[i].tracking_id>0);assert(ids.insert(f.out[i].tracking_id).second);assert(f.slot(f.out[i].tracking_id));}}
int main(){
    {
        Fixture f;const int id=f.confirm();f.peak(20,22);one(f,f.step(17666),id);
        assert(f.slot(id)->x-rawx(20)==1010);assert(f.slot(id)->dx==1010);
        one(f,f.step(42666),id);assert(f.slot(id)->x==rawx(22));assert(f.c->far_retired==0);
        pass("measured_101px_move_then_25ms_stationary_keeps_same_id");
    }
    {
        Fixture f;const int id=f.confirm();uint64_t now=9333;
        for(int col=21;col<=30;++col){now+=8333;f.peak(20,col);one(f,f.step(now),id);}
        for(int row=21;row<=26;++row){now+=8333;f.peak(row,30);one(f,f.step(now),id);}
        for(int col=29;col>=23;--col){now+=8333;f.peak(26,col);one(f,f.step(now),id);}
        assert(f.c->far_retired==0);pass("ordinary_drag_right_angle_and_reverse_keep_measured_identity");
    }
    {
        Fixture f;const int id=f.confirm();f.peak(20,22);one(f,f.step(17666),id);
        f.peak(20,20);one(f,f.step(25999),id);assert(f.slot(id)->x==rawx(20));
        assert(f.c->far_retired==0);pass("abrupt_101px_reversal_matches_last_actual_position");
    }
    {
        Fixture f;f.pair(15,15,25,35);assert(f.step(1000)==0);assert(f.step(9333)==2);unique(f,2);
        std::set<int> original{f.out[0].tracking_id,f.out[1].tracking_id};uint64_t now=9333;
        for(int d=1;d<=4;++d){now+=8333;f.pair(15,15+d,25,35-d);assert(f.step(now)==2);unique(f,2);assert((std::set<int>{f.out[0].tracking_id,f.out[1].tracking_id})==original);}
        assert(f.c->far_retired==0);pass("two_finger_global_assignment_retains_unique_existing_ids");
    }
    {
        Fixture f;f.pair(20,20,20,26);assert(f.step(1000)==0);assert(f.step(9333)==2);
        const int a=f.out[0].tracking_id,b=f.out[1].tracking_id;f.peak(20,23);
        assert(f.step(17666)==1);unique(f,1);assert(f.out[0].tracking_id==a || f.out[0].tracking_id==b);
        pass("one_shared_peak_cannot_be_assigned_to_two_fingers");
    }
    for(int delta: {239,240,241}){
        Fixture f;const int id=f.confirm();f.peak(20,20,180);one(f,f.step(17666),id);assert(f.slot(id)->missed==1);
        f.targetX(20,rawx(20)+delta);const int n=f.step(21999);
        if(delta<=240){one(f,n,id);assert(f.slot(id)->x==rawx(20)+delta);assert(f.slot(id)->missed==0);}
        else {assert(n==0);assert(!f.slot(id));assert(f.c->far_retired==1);}
        pass(delta==239?"missed_rejoin_23p9px_inside_original_gate":delta==240?"missed_rejoin_24px_exact_original_gate":"missed_rejoin_24p1px_outside_original_gate_retires");
    }
    for(int delta: {1999,2000,2001}){
        Fixture f;const int id=f.confirm();f.targetX(20,rawx(20)+delta);const int n=f.step(17666);
        if(delta<=2000){one(f,n,id);assert(f.slot(id)->x==rawx(20)+delta);assert(f.c->far_retired==0);}
        else {assert(n==0);assert(!f.slot(id));assert(f.c->far_retired==1);}
        pass(delta==1999?"normal_gate_199p9px_inside":delta==2000?"normal_gate_200px_existing_real_column_wins_dummy_cost_tie":"normal_gate_200p1px_outside_retires");
    }
    {
        Fixture f;const int id=f.confirm(20,16);f.peak(20,18);one(f,f.step(17666),id);
        assert(f.slot(id)->dx>1000);f.peak(20,23);assert(rawx(23)-rawx(18)>2000);
        assert(f.step(25999)==0);assert(!f.slot(id));assert(f.c->far_retired==1);
        pass("documented_cost_continuation_over_200px_breaks_without_prediction");
    }
    {
        Fixture f;const int id=f.confirm();const int prior=f.slot(id)->rx;f.peak(20,21,280);
        one(f,f.step(17666),id);assert(f.slot(id)->x==rawx(21));assert(f.slot(id)->rx==prior);
        assert(f.out[0].x==prior && f.slot(id)->last_observed_us==17666 && f.slot(id)->missed==0);
        pass("matched_weak_follow_freeze_and_observation_refresh_are_unchanged");
    }
    {
        Fixture f;const int id=f.confirm();f.flat();assert(f.step(17666)==0);assert(!f.slot(id));
        assert(f.c->ends[NVT_MISS_NONE]==1 && f.c->observation_cancelled==0);
        f.peak(20,20);assert(f.step(25999)==0);assert(f.step(34332)==1);assert(f.out[0].tracking_id!=id);
        pass("observed_empty_m_ends_id_then_requires_new_two_scan_start");
    }
    {
        Fixture f;const int id=f.confirm();const auto before=*f.slot(id);
        for(uint64_t t=13500;t<109333;t+=4167){const int e=f.expire(t);assert(e==-1);assert(f.frame(t,0x1d)==TouchEngine::SpecialP);assert(f.slot(id));assert(f.slot(id)->x==before.x && f.slot(id)->y==before.y && f.slot(id)->age==before.age && f.slot(id)->last_observed_us==before.last_observed_us);}
        assert(f.expire(109333)==0);assert(!f.slot(id));assert(f.c->observation_cancelled==1);
        assert(f.frame(109334,0x1d)==TouchEngine::SpecialP);assert(f.expire(109335)==-1);
        pass("p_frames_never_move_refresh_or_revive_timed_out_identity");
    }
    {
        Fixture f;f.peak(20,20);assert(f.step(1000)==0);assert(f.expire(25999)==-1);assert(f.c->slots[0].active);
        assert(f.step(26000)==0);assert(f.c->pending_expired==1);assert(f.c->slots[0].age==1);
        assert(f.step(34333)==1);pass("25ms_pending_boundary_preserves_original_two_observation_rule");
    }
    std::printf("{\"status\":\"PASS_HOST_SYNTHETIC_NOT_HARDWARE\",\"route\":\"B-measured-position\",\"tests\":%u}\n",passes);
}
