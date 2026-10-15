#include <stdio.h>

int main() {
    long long bound_limit;
    long long aggregate_sum = 0;
    if (scanf("%lld", &bound_limit) != 1) return 0;
    for (long long idx = 1; idx < bound_limit; idx++) {
        if (idx % 3 == 0 || idx % 5 == 0) {
            aggregate_sum = aggregate_sum + idx;
        }
    }
    printf("%lld\n", aggregate_sum);
    return 0;
}
