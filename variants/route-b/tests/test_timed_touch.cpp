#include "TouchEngine.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
extern "C" {
void *baseline_create(void);
void baseline_destroy(void *);
int baseline_step(void *,const int16_t *,unsigned,nvt_contact *,int);
}
static unsigned passes;
static void pass(const char *name){++passes;std::printf("PASS %s\n",name);}
struct Fixture {
    std::unique_ptr<nvt_touch_core> c{new nvt_touch_core};TouchEngine engine{c.get()};
    int16_t m[NVT_NODES],decoded[NVT_NODES];uint8_t raw[NVT_THP_FRAME_LEN];nvt_contact out[NVT_SLOTS];
    unsigned counter=0;
    Fixture(){nvt_touch_reset(c.get());flat();build(2,0);assert(engine.frame(raw,sizeof raw,0,decoded,out,NVT_SLOTS)==-1);}
    void flat(){for(auto &v:m)v=5000;}
    void peak(int row,int col,int amount=1000){flat();m[row*NVT_COLUMNS+col]=(int16_t)(5000+amount);}
    void build(unsigned type=4,unsigned dt=0){
        std::memset(raw,0,sizeof raw);++counter;raw[259]=(uint8_t)counter;raw[260]=(uint8_t)(counter>>8);
        raw[261]=0x34;raw[262]=0x12;raw[269]=0xcb;raw[270]=0xed;
        raw[265]=0x44;raw[266]=0x33;raw[267]=0x22;raw[268]=0x11;
        raw[273]=0xbb;raw[274]=0xcc;raw[275]=0xdd;raw[276]=0xee;raw[281]=(uint8_t)type;raw[313]=(uint8_t)dt;
        std::memcpy(raw+321,m,sizeof m);
    }
    int frame(uint64_t now,unsigned dt=0){build(4,dt);return engine.frame(raw,sizeof raw,now,decoded,out,NVT_SLOTS);}
    int expire(uint64_t now){return engine.expire(now,out,NVT_SLOTS);}
    int step(uint64_t now,unsigned dt=0){int cancelled=expire(now);(void)cancelled;return frame(now,dt);}
    int confirm(uint64_t start=1000,int row=20,int col=20){peak(row,col);assert(step(start)==0);assert(step(start+8333)==1);return out[0].tracking_id;}
};
static int rawx(int col){return nvt_touch_map_edge_axis(nvt_touch_column_center(col)*NVT_SUPER_RESOLUTION,NVT_LONG_AXIS_MAX,0);}
int main(){
    {
        Fixture f;f.peak(20,20);assert(f.step(1000)==0);assert(f.engine.waitUs(1000)==25000);
        assert(f.expire(25999)==-1);assert(f.c->slots[0].active);
        assert(f.expire(26000)==-1);assert(!f.c->slots[0].active);assert(f.c->pending_expired==1);
        assert(f.engine.waitUs(26000)==0);pass("pending_deadline_without_any_published_contact");
    }
    {
        Fixture f;f.peak(20,20);assert(f.step(1000)==0);
        for(uint64_t t=5167;t<501000;t+=4167)assert(f.step(t,0x1d)==TouchEngine::SpecialP);
        f.peak(20,21);assert(f.step(501000)==0);assert(f.step(509333)==1);
        assert(f.out[0].x==rawx(21));assert(f.c->pending_expired==1);pass("p_only_gap_cannot_confirm_500ms_old_origin");
    }
    {
        Fixture f;f.peak(20,20);assert(f.step(1000)==0);
        f.peak(20,21);assert(f.step(501000)==0);assert(f.step(509333)==1);assert(f.out[0].x==rawx(21));
        pass("complete_silence_cannot_confirm_old_hidden_slot");
    }
    {
        Fixture f;f.peak(39,20);assert(f.step(1000)==0);const int firstx=rawx(20);
        f.peak(39,21);assert(f.step(9333)==1);assert(f.out[0].x==firstx);
        const int firsty=nvt_touch_map_edge_axis(nvt_touch_row_center(39)*NVT_SUPER_RESOLUTION,NVT_SHORT_AXIS_MAX,1);
        assert(f.out[0].y==firsty);pass("normal_two_scan_edge_origin_is_preserved");
    }
    {
        Fixture f;f.confirm();const uint64_t last=9333;
        assert(f.expire(last+99999)==-1);assert(f.expire(last+100000)==0);
        assert(f.c->observation_cancelled==1);assert(f.expire(last+100001)==-1);
        assert(f.engine.waitUs(last+100001)==0);pass("visible_no_observation_cancel_once_at_100ms");
    }
    {
        Fixture f;int old=f.confirm();
        for(uint64_t t=13500;t<3500000;t+=4167){int e=f.expire(t);assert(e==-1||e==0);assert(f.frame(t,0x1d)==TouchEngine::SpecialP);}
        assert(f.c->observation_cancelled==1);f.peak(20,21);assert(f.step(3500000)==0);assert(f.step(3508333)==1);
        assert(f.out[0].tracking_id!=old);pass("long_p_stream_cancels_once_then_restarts_new_path");
    }
    {
        Fixture f;int old=f.confirm();f.peak(20,25);
        assert(f.step(17666)==0);assert(f.c->far_retired==1);assert(f.step(25999)==1);
        assert(f.out[0].tracking_id!=old);assert(f.step(34332)==1);assert(f.step(42665)==1);
        pass("far_single_peak_does_not_publish_old_and_new_ids_together");
    }
    {
        Fixture f;f.confirm();f.peak(20,20,180);
        assert(f.step(17666)==1);assert(f.c->slots[0].missed==1);assert(f.expire(34332)==-1);
        assert(f.expire(34333)==0);assert(f.c->dropout_expired==1);pass("weak_dropout_has_real_25ms_budget");
    }
    {
        Fixture f;f.confirm();f.flat();assert(f.step(17666)==0);assert(f.c->ends[NVT_MISS_NONE]==1);
        pass("real_empty_ordinary_matrix_still_releases_immediately");
    }
    {
        Fixture f;f.confirm();assert(f.expire(100)==0);assert(f.c->clock_rebases==1);
        f.peak(20,21);assert(f.step(200)==0);assert(f.step(8533)==1);pass("clock_rollback_cancels_instead_of_underflow_holding");
    }
    {
        Fixture f;f.peak(20,20);assert(f.step(1000)==0);std::memset(f.decoded,0x7c,sizeof f.decoded);
        auto before=std::make_unique<nvt_touch_core>();std::memcpy(before.get(),f.c.get(),sizeof(*before));
        int16_t sentinel[NVT_NODES];std::memcpy(sentinel,f.decoded,sizeof sentinel);
        f.build(4,0x1d);f.raw[329]=0x0c;f.raw[330]=0x17;
        assert(f.engine.frame(f.raw,sizeof f.raw,2000,f.decoded,f.out,NVT_SLOTS)==TouchEngine::SpecialP);
        assert(!std::memcmp(before.get(),f.c.get(),sizeof(*before)));assert(!std::memcmp(sentinel,f.decoded,sizeof sentinel));
        pass("actual_production_classifier_p_never_mutates_core_reference_or_matrix");
    }
    {
        Fixture f;f.build();f.raw[269]^=1;assert(f.engine.frame(f.raw,sizeof f.raw,1,f.decoded,f.out,NVT_SLOTS)==TouchEngine::Rejected);
        pass("production_engine_rejects_invalid_header");
    }
    {
        static_assert(NVT_THP_FRAME_LEN==5417,"raw wire length changed");
        static_assert(NVT_THP_MATRIX_OFFSET==321,"ordinary matrix offset changed");
        Fixture f;f.m[0]=-32768;f.m[1]=32767;f.m[1200]=-1;f.m[2399]=12345;
        f.build();assert(f.raw[321]==0 && f.raw[322]==0x80);assert(f.raw[323]==0xff && f.raw[324]==0x7f);
        const int n=f.engine.frame(f.raw,sizeof f.raw,1000,f.decoded,f.out,NVT_SLOTS);assert(n>=-1);
        assert(!std::memcmp(f.m,f.decoded,sizeof f.m));
        pass("raw_5417_bytes_signed_little_endian_ordinary_matrix_exact");
    }
    {
        Fixture f;f.confirm();auto before=std::make_unique<nvt_touch_core>();std::memcpy(before.get(),f.c.get(),sizeof(*before));
        assert(nvt_touch_process_timed(f.c.get(),f.m,3,999999,f.out,NVT_SLOTS)==-1);
        assert(!std::memcmp(before.get(),f.c.get(),sizeof(*before)));
        pass("direct_timed_invalid_type_does_not_consume_state_or_id_quarantine");
    }
    {
        Fixture f;f.confirm();f.build();
        auto before=std::make_unique<nvt_touch_core>();std::memcpy(before.get(),f.c.get(),sizeof(*before));
        nvt_contact saved[NVT_SLOTS];std::memset(f.out,0x5a,sizeof f.out);std::memcpy(saved,f.out,sizeof saved);
        const size_t badLengths[]={0,5416,5418};
        // Length is checked before even a valid pointer's header is inspected.
        for(size_t len:badLengths){assert(f.engine.frame(f.raw,len,999999,f.decoded,f.out,NVT_SLOTS)==TouchEngine::Rejected);
            assert(!std::memcmp(before.get(),f.c.get(),sizeof(*before)));assert(!std::memcmp(saved,f.out,sizeof saved));}
        uint8_t oneByte=0;assert(f.engine.frame(&oneByte,1,999999,f.decoded,f.out,NVT_SLOTS)==TouchEngine::Rejected);
        pass("production_engine_exact_raw_length_before_any_header_access");
    }
    {
        Fixture f;f.confirm();uint64_t now=9333;
        auto bounds=[&](int n){assert(n>=0 && n<=NVT_SLOTS);
            for(int i=0;i<n;++i){assert(f.out[i].x>=0 && f.out[i].x<NVT_LONG_AXIS_MAX);assert(f.out[i].y>=0 && f.out[i].y<NVT_SHORT_AXIS_MAX);}
            for(const auto &slot:f.c->slots)if(slot.active){assert(slot.fx>=0 && slot.fx<16L*NVT_LONG_AXIS_MAX);assert(slot.fy>=0 && slot.fy<16L*NVT_SHORT_AXIS_MAX);}
        };
        // Adversarial timing is synthetic, not a sensor scan-rate claim.
        for(unsigned i=0;i<1200;++i){now+=i%3==0?0:i%3==1?1:100;f.peak(20,20+(i&1),27767);bounds(f.step(now));}
        // Set the last displacement to zero, then exercise almost100ms dt while
        // a visible slot remains inside its explicit cancellation budget.
        for(unsigned i=0;i<20;++i){now+=100;f.peak(20,20,27767);bounds(f.step(now));}
        now+=99999;f.peak(20,20,27767);bounds(f.step(now));
        // Across extreme axis changes, far retirement is permitted but overflow
        // or an out-of-range centroid/filter value is never permitted.
        const int rows[]={0,39,0,39},cols[]={0,59,59,0};
        for(unsigned i=0;i<80;++i){now+=8333;f.peak(rows[i%4],cols[i%4],27767);bounds(f.step(now));}
        pass("timed_filter_dt0_dt1_small_to_99999us_and_extreme_signed_peak_bounds");
    }
    {
        auto current=std::make_unique<nvt_touch_core>();nvt_touch_reset(current.get());void *old=baseline_create();assert(old);
        int16_t matrix[NVT_NODES];nvt_contact a[NVT_SLOTS]{},b[NVT_SLOTS]{};unsigned comparisons=0;
        for(unsigned frame=0;frame<1200;++frame){
            for(auto &v:matrix)v=5000;
            if(frame%100>=5 && frame%100<80){unsigned row=10+(frame/100)%10,col=10+(frame%60);matrix[row*NVT_COLUMNS+col]=6000;}
            if(frame%150>30 && frame%150<90)matrix[25*NVT_COLUMNS+40]=5800;
            const unsigned type=frame==0?2:4;
            int na=nvt_touch_process(current.get(),matrix,type,a,NVT_SLOTS),nb=baseline_step(old,matrix,type,b,NVT_SLOTS);
            assert(na==nb);if(na>0)assert(!std::memcmp(a,b,(size_t)na*sizeof a[0]));++comparisons;
        }
        baseline_destroy(old);assert(comparisons==1200);pass("legacy_api_1200_matrix_outputs_equal_exact_author_core");
    }
    std::printf("{\"status\":\"PASS_HOST_SYNTHETIC_NOT_HARDWARE\",\"tests\":%u,\"policy\":4}\n",passes);
}
