#include <stdio.h>

// Gauss closed-form arithmetic progression formula: O(1) time
long long sum_div(long long m, long long k) {
    long long p = m / k;
    return k * p * (p + 1) / 2;
}

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    if (n <= 3) {
        printf("0\n");
        return 0;
    }
    long long m = n - 1;
    long long ans = sum_div(m, 3) + sum_div(m, 5) - sum_div(m, 15);
    printf("%lld\n", ans);
    return 0;
}
