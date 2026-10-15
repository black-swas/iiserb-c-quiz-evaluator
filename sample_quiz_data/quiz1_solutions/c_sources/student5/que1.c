#include <stdio.h>

// Direct byte-pointer traversal across integer memory representation
int main() {
    unsigned int n;
    if (scanf("%u", &n) != 1) return 0;
    unsigned char *ptr = (unsigned char*)&n;
    int bits = 0;
    for (int i = 0; i < 4; i++) {
        unsigned char b = *(ptr + i);
        while (b > 0) {
            bits += (b & 1);
            b >>= 1;
        }
    }
    printf("%d\n", bits);
    return 0;
}
