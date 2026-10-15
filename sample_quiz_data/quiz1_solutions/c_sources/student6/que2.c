#include <stdio.h>

int main() {
    long long n;
    int s = 0;
    if (scanf("%lld", &n) == 1) {
        while (n > 1) {
            n = (n & 1) ? (3 * n + 1) : (n >> 1);
            s++;
        }
        printf("%d\n", s);
    }
    return 0;
}
