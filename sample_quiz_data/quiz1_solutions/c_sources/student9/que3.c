#include <stdio.h>

int main() {
    long long max_n;
    long long tot_sum = 0;
    if (scanf("%lld", &max_n) != 1) return 0;
    for (long long k = 1; k < max_n; k++) {
        if (k % 3 == 0 || k % 5 == 0) {
            tot_sum = tot_sum + k;
        }
    }
    printf("%lld\n", tot_sum);
    return 0;
}
