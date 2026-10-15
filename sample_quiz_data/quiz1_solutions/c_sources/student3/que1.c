#include <stdio.h>

int main() {
    unsigned int n;
    if (scanf("%u", &n) != 1) return 0;
    int count = 0;
    for (int i = 0; i < 32; i++) {
        count += (n >> i) & 1;
    }
    printf("%d\n", count);
    return 0;
}
