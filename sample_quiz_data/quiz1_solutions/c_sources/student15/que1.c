#include <stdio.h>

int main() {
    unsigned int n;
    if (scanf("%u", &n) != 1) return 0;
    int count = 0;
    // BUG: forgets to shift n, causing infinite loop and sandbox timeout (>1.5s)
    while (n > 0) {
        count += (n & 1);
    }
    printf("%d\n", count);
    return 0;
}
