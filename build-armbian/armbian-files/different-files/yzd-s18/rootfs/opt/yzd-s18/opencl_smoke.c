/* GPU-only OpenCL correctness/stability check; CL 1.2 API on Mali r44p0. */
#define _POSIX_C_SOURCE 200809L
#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define N (1u << 20)
#define CHECK(call) do { cl_int check_status=(call); if(check_status!=CL_SUCCESS) { \
    fprintf(stderr,"%s failed: %d (line %d)\n",#call,check_status,__LINE__); return 1; } } while(0)
static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC,&t);
    return t.tv_sec+t.tv_nsec/1e9;
}
int main(int argc,char **argv) {
    unsigned seconds=0;
    if(argc>2) { fprintf(stderr,"Usage: %s [minimum-duration-seconds]\n",argv[0]); return 2; }
    if(argc==2) {
        char *end;
        unsigned long val=strtoul(argv[1],&end,10);
        if(!*argv[1] || *end || val>86400) { fprintf(stderr,"Invalid duration\n"); return 2; }
        seconds=(unsigned)val;
    }
    cl_uint count=0;
    CHECK(clGetPlatformIDs(0,NULL,&count));
    if(!count) { fprintf(stderr,"No OpenCL platform\n"); return 1; }
    cl_platform_id *platforms=calloc(count,sizeof(*platforms));
    if(!platforms) return 1;
    CHECK(clGetPlatformIDs(count,platforms,NULL));
    cl_device_id device=NULL;
    cl_platform_id platform=NULL;
    char name[256]={0};
    for(cl_uint i=0;i<count;i++) {
        cl_uint devices=0;
        cl_int e=clGetDeviceIDs(platforms[i],CL_DEVICE_TYPE_GPU,0,NULL,&devices);
        if(e!=CL_SUCCESS || !devices) continue;
        cl_device_id *ids=calloc(devices,sizeof(*ids));
        if(!ids) return 1;
        CHECK(clGetDeviceIDs(platforms[i],CL_DEVICE_TYPE_GPU,devices,ids,NULL));
        for(cl_uint j=0;j<devices;j++) {
            CHECK(clGetDeviceInfo(ids[j],CL_DEVICE_NAME,sizeof(name),name,NULL));
            if(strstr(name,"Mali") && strstr(name,"G31")) { device=ids[j]; platform=platforms[i]; break; }
        }
        free(ids);
        if(device) break;
    }
    free(platforms);
    if(!device) { fprintf(stderr,"No Mali G31 GPU device; CPU fallback is forbidden\n"); return 1; }
    cl_bool available=CL_FALSE,compiler=CL_FALSE;
    CHECK(clGetDeviceInfo(device,CL_DEVICE_AVAILABLE,sizeof(available),&available,NULL));
    CHECK(clGetDeviceInfo(device,CL_DEVICE_COMPILER_AVAILABLE,sizeof(compiler),&compiler,NULL));
    if(!available || !compiler) { fprintf(stderr,"GPU/compiler unavailable\n"); return 1; }
    char version[256],driver[256];
    CHECK(clGetDeviceInfo(device,CL_DEVICE_VERSION,sizeof(version),version,NULL));
    CHECK(clGetDeviceInfo(device,CL_DRIVER_VERSION,sizeof(driver),driver,NULL));
    printf("GPU=%s; device_version=%s; driver=%s\n",name,version,driver);
    cl_context_properties props[]={CL_CONTEXT_PLATFORM,(cl_context_properties)platform,0};
    cl_int e;
    cl_context context=clCreateContext(props,1,&device,NULL,NULL,&e); CHECK(e);
    cl_command_queue queue=clCreateCommandQueue(context,device,CL_QUEUE_PROFILING_ENABLE,&e); CHECK(e);
    const char *source="__kernel void add(__global const uint *a,__global const uint *b,__global uint *c) {size_t i=get_global_id(0);c[i]=a[i]+b[i];}";
    cl_program program=clCreateProgramWithSource(context,1,&source,NULL,&e); CHECK(e);
    e=clBuildProgram(program,1,&device,"-cl-std=CL1.2",NULL,NULL);
    if(e!=CL_SUCCESS) {
        size_t size=0;
        clGetProgramBuildInfo(program,device,CL_PROGRAM_BUILD_LOG,0,NULL,&size);
        char *log=calloc(size+1,1);
        if(log) { clGetProgramBuildInfo(program,device,CL_PROGRAM_BUILD_LOG,size,log,NULL); fprintf(stderr,"Build log: %s\n",log); free(log); }
        CHECK(e);
    }
    cl_kernel kernel=clCreateKernel(program,"add",&e); CHECK(e);
    const size_t bytes=N*sizeof(cl_uint),global=N;
    cl_uint *a=malloc(bytes),*b=malloc(bytes),*c=malloc(bytes);
    if(!a || !b || !c) return 1;
    for(size_t i=0;i<N;i++) { a[i]=(cl_uint)(i&1023); b[i]=(cl_uint)((i*3)&1023); }
    cl_mem ba=clCreateBuffer(context,CL_MEM_READ_ONLY|CL_MEM_COPY_HOST_PTR,bytes,a,&e); CHECK(e);
    cl_mem bb=clCreateBuffer(context,CL_MEM_READ_ONLY|CL_MEM_COPY_HOST_PTR,bytes,b,&e); CHECK(e);
    cl_mem bc=clCreateBuffer(context,CL_MEM_WRITE_ONLY,bytes,NULL,&e); CHECK(e);
    CHECK(clSetKernelArg(kernel,0,sizeof(ba),&ba));
    CHECK(clSetKernelArg(kernel,1,sizeof(bb),&bb));
    CHECK(clSetKernelArg(kernel,2,sizeof(bc),&bc));
    double start=now(),last=start;
    unsigned long runs=0;
    do {
        CHECK(clEnqueueNDRangeKernel(queue,kernel,1,NULL,&global,NULL,0,NULL,NULL));
        CHECK(clEnqueueReadBuffer(queue,bc,CL_TRUE,0,bytes,c,0,NULL,NULL));
        for(size_t i=0;i<N;i++) {
            if(c[i]!=a[i]+b[i]) { fprintf(stderr,"Mismatch run=%lu index=%zu expected=%u actual=%u\n",runs,i,a[i]+b[i],c[i]); return 1; }
        }
        runs++;
        if(now()-last>=30) { printf("verified_runs=%lu elapsed=%.1fs\n",runs,now()-start); fflush(stdout); last=now(); }
    } while(runs<100 || now()-start<seconds);
    CHECK(clFinish(queue));
    printf("PASS: %lu runs x %u integers; elapsed=%.3fs; all results match\n",runs,N,now()-start);
    clReleaseMemObject(ba);clReleaseMemObject(bb);clReleaseMemObject(bc);
    clReleaseKernel(kernel);clReleaseProgram(program);clReleaseCommandQueue(queue);clReleaseContext(context);
    free(a);free(b);free(c);
    return 0;
}
