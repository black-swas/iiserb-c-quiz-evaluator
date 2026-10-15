#include <stdio.h>

int main() {
    long long num_seq;
    int steps_cnt = 0;
    if (scanf("%lld", &num_seq) != 1) return 0;
    while (num_seq > 1) {
        if (num_seq % 2 == 0) {
            num_seq = num_seq / 2;
        } else {
            num_seq = 3 * num_seq + 1;
        }
        steps_cnt = steps_cnt + 1;
    }
    printf("%d\n", steps_cnt);
    return 0;
}
