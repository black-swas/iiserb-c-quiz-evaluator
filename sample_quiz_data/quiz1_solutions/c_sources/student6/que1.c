#include <stdio.h>

int main() {
    unsigned int n;
    int c = 0;
    if (scanf("%u", &n) == 1) {
        for (; n; c += (n & 1), n >>= 1);
        printf("%d\n", c);
    }
    return 0;
}
