#include <stdio.h>

// Brian Kernighan's bitwise algorithm: clears lowest set bit in O(set_bits)
int main() {
    unsigned int n;
    if (scanf("%u", &n) != 1) return 0;
    int count = 0;
    while (n) {
        n &= (n - 1);
        count++;
    }
    printf("%d\n", count);
    return 0;
}
