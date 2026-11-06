// Tests the exact production implementation, not a copied matcher.
#include "../device/drivers/ShengNovatekTouch/NvtTouchCore.c"
void route_a_probe(const struct nvt_touch_core *core,const struct nvt_contact *found,int n,int *match,long *detail) {
    int active=0;for(int i=0;i<NVT_SLOTS;++i)active+=core->slots[i].active!=0;
    struct track_projection p[NVT_SLOTS];project_tracks(core,found,n,active<=3,p);
    assign_tracks(core,found,n,match);
    detail[0]=p[0].original_x;detail[1]=p[0].original_y;detail[2]=p[0].x;detail[3]=p[0].y;
    detail[4]=p[0].fallback;detail[5]=p[0].ambiguous;detail[6]=track_cost(&core->slots[0],found,n,0,&p[0]);
    detail[7]=track_cost(&core->slots[0],found,n,n,&p[0]);
}
