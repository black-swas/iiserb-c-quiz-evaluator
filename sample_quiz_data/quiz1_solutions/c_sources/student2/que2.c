#include <stdio.h>

// Bitwise parity check and shifts for Collatz
int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    int steps = 0;
    while (n > 1) {
        if (n & 1) {
            n = (n << 1) + n + 1;
        } else {
            n >>= 1;
        }
        steps++;
    }
    printf("%d\n", steps);
    return 0;
}
