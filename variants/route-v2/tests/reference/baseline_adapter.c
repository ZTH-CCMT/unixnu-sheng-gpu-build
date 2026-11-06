#include "NvtTouchCore.h"
#include <stdlib.h>
void *baseline_create(void){struct nvt_touch_core *c=malloc(sizeof(*c));if(c)nvt_touch_reset(c);return c;}
void baseline_destroy(void *c){free(c);}
int baseline_step(void *c,const int16_t *m,unsigned type,struct nvt_contact *out,int max){return nvt_touch_process(c,m,type,out,max);}
