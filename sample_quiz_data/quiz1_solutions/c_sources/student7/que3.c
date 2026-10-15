#include <stdio.h>

int main() {
    long long limit;
    if (scanf("%lld", &limit) != 1) return 0;
    long long total_sum = 0;
    for (long long i = 1; i < limit; i++) {
        if (i % 3 == 0 || i % 5 == 0) {
            total_sum = total_sum + i;
        }
    }
    printf("%lld\n", total_sum);
    return 0;
}
