#include <stdio.h>

int main() {
    int n;
    if (scanf("%d", &n) != 1) return 0;
    // BUG: 32-bit int accumulator overflows on n=50000 and n=1000000
    int sum = 0;
    for (int i = 1; i < n; i++) {
        if (i % 3 == 0 || i % 5 == 0) sum += i;
    }
    printf("%d\n", sum);
    return 0;
}
