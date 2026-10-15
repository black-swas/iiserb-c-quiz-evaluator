#include <stdio.h>

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    long long sum = 0;
    for (long long i = 1; i < n; i++) {
        if ((i % 3 == 0) || (i % 5 == 0)) {
            sum += i;
        }
    }
    printf("%lld\n", sum);
    return 0;
}
