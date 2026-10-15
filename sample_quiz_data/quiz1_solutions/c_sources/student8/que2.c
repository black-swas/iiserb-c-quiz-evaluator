#include <stdio.h>

int main() {
    long long hail_val;
    int step_tracker = 0;
    if (scanf("%lld", &hail_val) != 1) return 0;
    while (hail_val > 1) {
        if (hail_val % 2 == 0) {
            hail_val = hail_val / 2;
        } else {
            hail_val = 3 * hail_val + 1;
        }
        step_tracker = step_tracker + 1;
    }
    printf("%d\n", step_tracker);
    return 0;
}
