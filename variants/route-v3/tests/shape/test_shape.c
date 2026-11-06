// SPDX-License-Identifier: Apache-2.0
#include "NvtShapeMetricsInline.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
static int delta[NVT_SHAPE_NODES],labels[NVT_SHAPE_NODES];
static void clear(void){for(unsigned i=0;i<NVT_SHAPE_NODES;++i){delta[i]=0;labels[i]=-1;}}
static void point(unsigned r,unsigned c,int value){delta[r*NVT_SHAPE_COLUMNS+c]=value;labels[r*NVT_SHAPE_COLUMNS+c]=0;}
static void box(unsigned r,unsigned c,unsigned h,unsigned w,int value){for(unsigned y=r;y<r+h;++y)for(unsigned x=c;x<c+w;++x)point(y,x,value);}
static struct nvt_shape_metrics measure(int floor){struct nvt_shape_metrics m;assert(nvt_shape_measure(delta,labels,0,floor,&m)==1);return m;}
static void emit(const char *name,const struct nvt_shape_metrics *m){printf("{\"case\":\"%s\",\"support\":%u,\"rows\":%u,\"columns\":%u,\"roundness_q16\":%u,\"edge_flags\":%u,\"weight\":%llu}\n",name,m->support_nodes,m->support_rows,m->support_columns,m->roundness_q16,m->edge_flags,(unsigned long long)m->weight);}
int main(void){
 struct nvt_shape_metrics m,n;
 clear();point(17,29,500);m=measure(150);
 assert(m.labelled_nodes==1 && m.support_nodes==1 && m.support_rows==1 && m.support_columns==1);
 assert(m.mean_row_q16==17u*65536 && m.mean_column_q16==29u*65536 && m.roundness_q16==0 && m.spatial_rank==0 && m.effective_support_q16==65536);
 assert(m.background_nodes==8 && m.background_abs_mean_q16==0);emit("single_node_fake_no_trust_decision",&m);
 clear();box(10,20,2,2,400);m=measure(100);
 assert(m.support_nodes==4 && m.support_rows==2 && m.support_columns==2 && m.row_span==2 && m.column_span==2);
 assert(m.mean_row_q16==10u*65536+32768 && m.mean_column_q16==20u*65536+32768);
 assert(m.variance_row_q16==16384 && m.variance_column_q16==16384 && m.covariance_q16==0 && m.spatial_rank==2 && m.roundness_q16==65535 && m.effective_support_q16==4u*65536);emit("compact_2d",&m);
 clear();box(18,20,1,9,400);m=measure(100);
 assert(m.support_rows==1 && m.support_columns==9 && m.roundness_q16==0 && m.spatial_rank==1 && m.variance_row_q16==0);emit("ridge_1d",&m);
 clear();box(15,22,6,10,400);m=measure(100);assert(m.labelled_nodes==60 && m.support_nodes==60 && m.edge_flags==0);emit("palm_sized_measurement_no_classifier",&m);
 clear();box(15,0,5,3,400);m=measure(100);assert(m.edge_flags==NVT_SHAPE_EDGE_LEFT && m.row_span==5 && m.column_span==3);emit("edge_half_blob_flag_only",&m);
 clear();box(10,20,3,3,280);point(11,21,560);m=measure(70);
 for(unsigned i=0;i<NVT_SHAPE_NODES;++i)delta[i]*=2;n=measure(140);
 assert(m.mean_row_q16==n.mean_row_q16 && m.mean_column_q16==n.mean_column_q16 && m.variance_row_q16==n.variance_row_q16 && m.variance_column_q16==n.variance_column_q16 && m.covariance_q16==n.covariance_q16 && m.roundness_q16==n.roundness_q16 && m.effective_support_q16==n.effective_support_q16 && n.weight==2*m.weight);emit("amplitude_scaling_geometry_invariance",&n);
 clear();box(10,20,2,2,400);delta[9*NVT_SHAPE_COLUMNS+20]=-30;delta[9*NVT_SHAPE_COLUMNS+21]=30;
 point(9,19,65535);labels[9*NVT_SHAPE_COLUMNS+19]=1;m=measure(100);
 assert(m.background_nodes==11 && m.background_abs_max==30 && m.background_mean_q16==0 && m.background_abs_mean_q16==(60u*65536)/11);emit("local_ring_excludes_neighbor_blob",&m);
 clear();point(1,1,65535);delta[0]=-65535;m=measure(0);
 assert(m.peak_minus_background_abs_q16>INT32_MAX && m.background_mean_q16<0);emit("signed_background_and_contrast_ranges",&m);
 clear();box(0,0,NVT_SHAPE_ROWS,NVT_SHAPE_COLUMNS,65535);m=measure(0);
 assert(m.support_nodes==2400 && m.weight==UINT64_C(157284000) && m.effective_support_q16==2400u*65536 && m.edge_flags==15 && m.background_nodes==0);emit("full_matrix_maximum_no_overflow",&m);
 clear();point(0,0,65535);point(39,59,65535);m=measure(0);
 assert(m.support_nodes==2 && m.support_rows==2 && m.support_columns==2 && m.mean_row_q16==19u*65536+32768 && m.mean_column_q16==29u*65536+32768);emit("diagonal_extremes_nearly_degenerate",&m);
  clear();point(36,0,100);point(37,2,107);point(38,4,299);m=measure(89);
 assert(m.spatial_rank==1 && m.roundness_q16>0 && m.covariance_determinant_q32>0);emit("collinear_Q16_rounding_cannot_decide_2D",&m);
 clear();box(0,20,1,3,299);m=measure(89);
 assert(m.spatial_rank==1 && m.support_nodes==3 && m.edge_flags==NVT_SHAPE_EDGE_TOP);emit("edge_three_run_is_not_proof_of_finger",&m);
 clear();point(5,5,100);memset(&m,0xa5,sizeof m);assert(nvt_shape_measure(delta,labels,0,100,&m)==0);memset(&n,0,sizeof n);assert(memcmp(&m,&n,sizeof m)==0);emit("zero_weight_clears_output",&m);
 clear();delta[2399]=65536;memset(&m,0xa5,sizeof m);assert(nvt_shape_measure(delta,labels,0,0,&m)==-1 && memcmp(&m,&n,sizeof m)==0);
 assert(nvt_shape_measure(NULL,labels,0,0,&m)==-1 && nvt_shape_measure(delta,labels,-1,0,&m)==-1 && nvt_shape_measure(delta,labels,0,-1,&m)==-1 && nvt_shape_measure(delta,labels,0,0,NULL)==-1);puts("{\"case\":\"invalid_input_refused_without_partial_output\"}");
 return 0;
}
