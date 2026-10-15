#include <stdio.h>

// Function to calculate set bits
int main() {
    unsigned int num;
    if (scanf("%u", &num) != 1) return 0;
    int total_ones = 0;
    while (num != 0) {
        if (num % 2 == 1) {
            total_ones++;
        }
        num = num / 2;
    }
    printf("%d\n", total_ones);
    return 0;
}
