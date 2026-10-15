#include <stdio.h>

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    long long total = 0;
    for (long long k = 3; k < n; k++) {
        if (k % 3 == 0 || k % 5 == 0) total += k;
    }
    printf("%lld\n", total);
    return 0;
}
