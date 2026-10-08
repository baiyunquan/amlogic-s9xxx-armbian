/* Native hardware identity, GLES raster readback and Vulkan queue checks. */
#define _POSIX_C_SOURCE 200809L
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <gbm.h>
#include <vulkan/vulkan.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static GLuint shader(GLenum type, const char *source)
{
    GLuint obj = glCreateShader(type);
    GLint okay = 0;
    glShaderSource(obj, 1, &source, NULL);
    glCompileShader(obj);
    glGetShaderiv(obj, GL_COMPILE_STATUS, &okay);
    if (!okay) {
        char log[2048];
        glGetShaderInfoLog(obj, sizeof(log), NULL, log);
        fprintf(stderr, "Shader compilation failed: %s\n", log);
        glDeleteShader(obj);
        return 0;
    }
    return obj;
}

static int gles(const char *path)
{
    int result = 1, fd = -1;
    struct gbm_device *gbm = NULL;
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    EGLConfig config;
    EGLint major = 0, minor = 0, count = 0;
    GLuint vertex = 0, fragment = 0, program = 0, vao = 0;
    const EGLint attrs[] = { EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR, EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE };
    const EGLint ctxattrs[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE };
    const EGLint pbattrs[] = { EGL_WIDTH, 64, EGL_HEIGHT, 64, EGL_NONE };
    unsigned char pixels[64 * 64 * 4];
    const char *vs = "#version 300 es\n"
        "const vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));"
        "void main(){gl_Position=vec4(p[gl_VertexID],0,1);}";
    const char *fs = "#version 300 es\nprecision highp float;"
        "out vec4 color;void main(){color=vec4(0.125,0.5,0.875,1);}";
#define EGL_REQUIRE(call) do { if (!(call)) { \
    fprintf(stderr, "%s failed: EGL 0x%x\n", #call, eglGetError()); goto done; } } while (0)
    fd = open(path, O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror(path); goto done; }
    gbm = gbm_create_device(fd);
    if (!gbm) { fprintf(stderr, "Cannot create GBM device\n"); goto done; }
    display = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    EGL_REQUIRE(display != EGL_NO_DISPLAY);
    EGL_REQUIRE(eglInitialize(display, &major, &minor));
    printf("EGL=%d.%d; vendor=%s; client APIs=%s\n", major, minor,
           eglQueryString(display, EGL_VENDOR), eglQueryString(display, EGL_CLIENT_APIS));
    EGL_REQUIRE(eglBindAPI(EGL_OPENGL_ES_API));
    EGL_REQUIRE(eglChooseConfig(display, attrs, &config, 1, &count) && count == 1);
    surface = eglCreatePbufferSurface(display, config, pbattrs);
    EGL_REQUIRE(surface != EGL_NO_SURFACE);
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, ctxattrs);
    EGL_REQUIRE(context != EGL_NO_CONTEXT);
    EGL_REQUIRE(eglMakeCurrent(display, surface, surface, context));
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("GL_VENDOR=%s; GL_RENDERER=%s; GL_VERSION=%s\n", glGetString(GL_VENDOR),
           renderer ? renderer : "NULL", glGetString(GL_VERSION));
    if (!renderer || !strstr(renderer, "Mali") || !strstr(renderer, "G31")) {
        fprintf(stderr, "Real Mali-G31 renderer required\n"); goto done;
    }
    vertex = shader(GL_VERTEX_SHADER, vs);
    fragment = shader(GL_FRAGMENT_SHADER, fs);
    if (!vertex || !fragment) goto done;
    program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    GLint linked = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "Shader program link failed\n"); goto done; }
    glUseProgram(program);
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glViewport(0, 0, 64, 64);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glFinish();
    if (glGetError() != GL_NO_ERROR) { fprintf(stderr, "GLES rendering error\n"); goto done; }
    const int expected[] = {32, 128, 223, 255};
    for (size_t i = 0; i < sizeof(pixels); i++) {
        if (abs((int)pixels[i] - expected[i % 4]) > 2) {
            fprintf(stderr, "Pixel byte %zu: got %u expected %d\n", i, pixels[i], expected[i % 4]);
            goto done;
        }
    }
    printf("PASS: GPU shader compiled and 4096 RGBA pixels verified\n");
    result = 0;
done:
    if (context != EGL_NO_CONTEXT) {
        if (vao) glDeleteVertexArrays(1, &vao);
        if (program) glDeleteProgram(program);
        if (vertex) glDeleteShader(vertex);
        if (fragment) glDeleteShader(fragment);
        eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        eglDestroyContext(display, context);
    }
    if (surface != EGL_NO_SURFACE) eglDestroySurface(display, surface);
    if (display != EGL_NO_DISPLAY) eglTerminate(display);
    if (gbm) gbm_device_destroy(gbm);
    if (fd >= 0) close(fd);
    return result;
#undef EGL_REQUIRE
}

static int vulkan(void)
{
    int result = 1;
    VkInstance instance = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkPhysicalDevice *devices = NULL;
    VkQueueFamilyProperties *families = NULL;
    uint32_t count = 0, nfamilies = 0, family = UINT32_MAX;
    VkApplicationInfo app = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "YZD-S18 graphics check", .apiVersion = VK_API_VERSION_1_2 };
    VkInstanceCreateInfo create = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app };
#define VK_REQUIRE(call) do { VkResult status_ = (call); if (status_ != VK_SUCCESS) { \
    fprintf(stderr, "%s failed: VkResult %d\n", #call, status_); goto done; } } while (0)
    VK_REQUIRE(vkCreateInstance(&create, NULL, &instance));
    VK_REQUIRE(vkEnumeratePhysicalDevices(instance, &count, NULL));
    if (!count) { fprintf(stderr, "No Vulkan GPU\n"); goto done; }
    devices = calloc(count, sizeof(*devices));
    if (!devices) goto done;
    VK_REQUIRE(vkEnumeratePhysicalDevices(instance, &count, devices));
    for (uint32_t i = 0; i < count; i++) {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(devices[i], &props);
        printf("Vulkan device=%s; vendor=0x%x; type=%d; API=%u.%u.%u\n", props.deviceName,
            props.vendorID, props.deviceType, VK_VERSION_MAJOR(props.apiVersion),
            VK_VERSION_MINOR(props.apiVersion), VK_VERSION_PATCH(props.apiVersion));
        if (strstr(props.deviceName, "Mali") && strstr(props.deviceName, "G31") &&
                props.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU) physical = devices[i];
    }
    if (physical == VK_NULL_HANDLE) { fprintf(stderr, "Mali-G31 Vulkan GPU required\n"); goto done; }
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &nfamilies, NULL);
    if (!nfamilies) goto done;
    families = calloc(nfamilies, sizeof(*families));
    if (!families) goto done;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &nfamilies, families);
    for (uint32_t i = 0; i < nfamilies; i++)
        if (families[i].queueCount && (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) { family = i; break; }
    if (family == UINT32_MAX) { fprintf(stderr, "No graphics queue\n"); goto done; }
    float priority = 1.0f;
    VkDeviceQueueCreateInfo queueinfo = { .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority };
    VkDeviceCreateInfo devinfo = { .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &queueinfo };
    VK_REQUIRE(vkCreateDevice(physical, &devinfo, NULL, &device));
    VkQueue queue = VK_NULL_HANDLE;
    vkGetDeviceQueue(device, family, 0, &queue);
    if (queue == VK_NULL_HANDLE) goto done;
    VK_REQUIRE(vkQueueWaitIdle(queue));
    printf("PASS: Vulkan logical device and graphics queue %u initialized\n", family);
    result = 0;
done:
    if (device != VK_NULL_HANDLE) vkDestroyDevice(device, NULL);
    free(families);
    free(devices);
    if (instance != VK_NULL_HANDLE) vkDestroyInstance(instance, NULL);
    return result;
#undef VK_REQUIRE
}

int main(int argc, char **argv)
{
    if (argc == 3 && !strcmp(argv[1], "gles")) return gles(argv[2]);
    if (argc == 2 && !strcmp(argv[1], "vulkan")) return vulkan();
    fprintf(stderr, "Usage: %s gles /dev/dri/cardN | vulkan\n", argv[0]);
    return 2;
}
