#include <stdio.h>

// Pure recursive set-bit counter without loops
int count_bits(unsigned int n) {
    if (n == 0) return 0;
    return (n & 1) + count_bits(n >> 1);
}

int main() {
    unsigned int n;
    if (scanf("%u", &n) != 1) return 0;
    printf("%d\n", count_bits(n));
    return 0;
}
