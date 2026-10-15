#include <stdio.h>

// Copied code with identifier renaming
int main() {
    unsigned int in_num;
    int bit_ans = 0;
    if (scanf("%u", &in_num) != 1) return 0;
    unsigned int n_copy = in_num;
    while (n_copy > 0) {
        if (n_copy % 2 == 1) {
            bit_ans = bit_ans + 1;
        }
        n_copy = n_copy / 2;
    }
    printf("%d\n", bit_ans);
    return 0;
}
