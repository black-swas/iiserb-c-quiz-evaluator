#include <stdio.h>

// Pure recursive Collatz step counter
int collatz(long long n) {
    if (n <= 1) return 0;
    if (n % 2 == 0) return 1 + collatz(n / 2);
    return 1 + collatz(3 * n + 1);
}

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    printf("%d\n", collatz(n));
    return 0;
}
