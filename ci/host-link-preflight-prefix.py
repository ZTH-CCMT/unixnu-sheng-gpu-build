#!/usr/bin/env python3
"""Drive the Turnip darwin backend through a real Vulkan instance against the host copy of the NativeAdreno kernel stack.

The kernel half is the real GPU context bring-up, VM, ring, submit and user-client code over software SMMU/CP peers
(tests/hostsim/host_gpu_service.cpp); an IOKit shim answers the backend's IOKit calls. Nothing here runs a shader or touches
hardware: the software CP retires every submission at once. Needs the host Turnip build (build-turnip-darwin.py --target host)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
kit = ROOT / 'drivers/Adreno740'
sim = kit / 'tests/hostsim'
out = ROOT / 'build/turnip-darwin-host'
out.mkdir(parents=True, exist_ok=True)
smmu = ROOT / 'kits/ArmSmmu4K'
library = ROOT / 'build/mesa-tu/src/freedreno/vulkan/libvulkan_freedreno.dylib'

includes = out / 'host-include'
for name in ['IOKit/IOTypes.h', 'IOKit/IOReturn.h', 'IOKit/IOBufferMemoryDescriptor.h', 'IOKit/IOLib.h', 'kern/task.h']:
    path = includes / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#include "XnuMemoryFixture.h"\n')

objects = []
for stem in ['ArmSmmu4KContext', 'ArmSmmu4KProgram', 'ArmSmmu4KLive', 'ArmSmmu4KStreams', 'ArmSmmu4KMmio']:
    obj = out / (stem + '.o')
    subprocess.run(['xcrun', 'clang', '-std=c11', '-O1', '-fPIC', '-c', smmu / (stem + '.c'), '-o', obj], check=True)
    objects.append(obj)
obj = out / 'AdrenoPM4.o'
subprocess.run(['xcrun', 'clang', '-std=c11', '-O1', '-fPIC', '-c', ROOT / 'kits/AdrenoPM4/AdrenoPM4.c', '-o', obj], check=True)
objects.append(obj)

service = out / 'host_gpu_service.o'
subprocess.run(['xcrun', 'clang++', '-std=c++23', '-O1', '-fPIC', '-I', includes, '-I', sim.parent, '-I', kit, '-I', smmu,
                '-I', ROOT / 'kits/AdrenoPM4', '-c', sim / 'host_gpu_service.cpp', '-o', service], check=True)
core = []
for name in ['NativeAdrenoMemory', 'NativeAdrenoSmmuMemory', 'NativeAdrenoVm', 'NativeAdrenoRing', 'NativeAdrenoSubmit',
             'NativeAdrenoUserClient', 'NativeAdrenoTimer', 'NativeAdrenoSmmuContext', 'NativeAdrenoGpuContext', 'NativeAdrenoPreempt']:
    obj = out / (name + '.o')
    subprocess.run(['xcrun', 'clang++', '-std=c++23', '-O1', '-fPIC', '-I', includes, '-I', sim.parent, '-I', kit, '-I', smmu,
                    '-I', ROOT / 'kits/AdrenoPM4', '-c', kit / (name + '.cpp'), '-o', obj], check=True)
    core.append(obj)
shim_obj = out / 'host_iokit_shim.o'
subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-fPIC', '-c', sim / 'host_iokit_shim.cpp', '-o', shim_obj], check=True)
shim = out / 'libhostiokit.dylib'
subprocess.run(['xcrun', 'clang++', '-dynamiclib', '-o', shim, service, shim_obj, *core, *objects,
                '-framework', 'IOKit', '-framework', 'CoreFoundation'], check=True)
